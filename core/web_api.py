from __future__ import annotations

import json
import os
import shutil
import subprocess
import locale
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class JarCallResult:
    returncode: int
    command: list[str]
    stdout: str
    stderr: str
    data: Optional[dict[str, Any]]
    success: Optional[bool]


class JarCallError(RuntimeError):
    def __init__(self, result: JarCallResult):
        msg = f"CLI call failed (code={result.returncode})"
        if result.data:
            detail = result.data.get("message") or result.data.get("error")
            if detail:
                msg += f": {detail}"
        elif result.stderr:
            msg += f": {result.stderr.strip()}"
        super().__init__(msg)
        self.result = result


class DouyinPmCliClient:
    """
    Python wrapper for:
      kol_dy_msg-1.0.4-SNAPSHOT-private-message-cli.jar

    Required init params:
      session_id, user_id, ms_token, verify_fp, fp, uifid

    Fixed (not exposed):
      output=json, quiet=true
    """

    _OUTPUT = "json"
    _QUIET = True

    def __init__(
        self,
        *,
        session_id: str,
        user_id: str,
        ms_token: str,
        verify_fp: str,
        fp: str,
        uifid: str,
        jar_path: Optional[str | Path] = None,
        java_path: Optional[str | Path] = None,
        timeout_sec: int = 60,
    ) -> None:
        # property setters (with validation)
        self.session_id = session_id
        self.user_id = user_id
        self.ms_token = ms_token
        self.verify_fp = verify_fp
        self.fp = fp
        self.uifid = uifid
        self.timeout_sec = timeout_sec

        self.java_path = Path(java_path) if java_path else self._auto_find_java()
        self.jar_path = (
            Path(jar_path)
            if jar_path
            else Path(__file__).parent.parent
            / "res"
            / "kol_dy_msg-1.0.4-SNAPSHOT-private-message-cli.jar"
        )

    # ---------- property helpers ----------
    @staticmethod
    def _must_non_empty(name: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required and cannot be blank")
        return value.strip()

    # ---------- required business fields ----------
    @property
    def session_id(self) -> str:
        return self._session_id

    @session_id.setter
    def session_id(self, value: str) -> None:
        self._session_id = self._must_non_empty("session_id", value)

    @property
    def user_id(self) -> str:
        return self._user_id

    @user_id.setter
    def user_id(self, value: str) -> None:
        self._user_id = self._must_non_empty("user_id", value)

    @property
    def ms_token(self) -> str:
        return self._ms_token

    @ms_token.setter
    def ms_token(self, value: str) -> None:
        self._ms_token = self._must_non_empty("ms_token", value)

    @property
    def verify_fp(self) -> str:
        return self._verify_fp

    @verify_fp.setter
    def verify_fp(self, value: str) -> None:
        self._verify_fp = self._must_non_empty("verify_fp", value)

    @property
    def fp(self) -> str:
        return self._fp

    @fp.setter
    def fp(self, value: str) -> None:
        self._fp = self._must_non_empty("fp", value)

    @property
    def uifid(self) -> str:
        return self._uifid

    @uifid.setter
    def uifid(self, value: str) -> None:
        self._uifid = self._must_non_empty("uifid", value)

    # ---------- runtime fields ----------
    @property
    def jar_path(self) -> Path:
        return self._jar_path

    @jar_path.setter
    def jar_path(self, value: str | Path) -> None:
        p = Path(value)
        if not p.exists():
            raise FileNotFoundError(f"jar not found: {p}")
        self._jar_path = p

    @property
    def java_path(self) -> Path:
        return self._java_path

    @java_path.setter
    def java_path(self, value: str | Path) -> None:
        p = Path(value)
        if not p.exists():
            raise FileNotFoundError(f"java not found: {p}")
        self._java_path = p

    @property
    def timeout_sec(self) -> int:
        return self._timeout_sec

    @timeout_sec.setter
    def timeout_sec(self, value: int) -> None:
        if int(value) <= 0:
            raise ValueError("timeout_sec must be > 0")
        self._timeout_sec = int(value)

    # ---------- auto path discovery ----------
    def _auto_find_java(self) -> Path:
        java = shutil.which("java")
        if java:
            return Path(java)

        java_home = os.getenv("JAVA_HOME")
        if java_home:
            exe = "java.exe" if os.name == "nt" else "java"
            candidate = Path(java_home) / "bin" / exe
            if candidate.exists():
                return candidate

        raise FileNotFoundError("java not found in PATH (and JAVA_HOME is invalid)")

    # ---------- unified call ----------
    @staticmethod
    def _to_cli_value(v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, bool):
            return "true" if v else "false"
        return str(v)

    import locale

    @staticmethod
    def _decode_bytes(raw: bytes) -> str:
        if not raw:
            return ""
        tried = []
        for enc in ("utf-8", locale.getpreferredencoding(False), "gb18030", "cp936"):
            if not enc or enc in tried:
                continue
            tried.append(enc)
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                pass
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _parse_json_from_stdout(stdout: str) -> Optional[dict[str, Any]]:
        s = (stdout or "").strip()
        if not s:
            return None
        try:
            obj = json.loads(s)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            pass

        # 兼容“前面有杂讯，最后一行才是 JSON”
        for line in reversed([x.strip() for x in s.splitlines() if x.strip()]):
            if line.startswith("{") and line.endswith("}"):
                try:
                    obj = json.loads(line)
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    continue
        return None

    def _call(
        self,
        msg_type: str,
        *,
        params: Optional[dict[str, Any]] = None,
        timeout_sec: Optional[int] = None,
        check: bool = True,
    ) -> JarCallResult:
        call_params: dict[str, Any] = {
            "sessionId": self.session_id,
            "userId": self.user_id,
            "msToken": self.ms_token,
            "verifyFp": self.verify_fp,
            "fp": self.fp,
            "uifid": self.uifid,
            "type": msg_type,
            "output": self._OUTPUT,
            "quiet": self._QUIET,
        }
        if params:
            call_params.update(params)

        cmd = [str(self.java_path), "-jar", str(self.jar_path)]
        for k, v in call_params.items():
            vv = self._to_cli_value(v)
            if vv is None:
                continue
            key = k[2:] if k.startswith("--") else k
            cmd.extend([f"--{key}", vv])

        p = subprocess.run(
            cmd,
            capture_output=True,
            text=False,
            timeout=timeout_sec or self.timeout_sec,
        )

        stdout = self._decode_bytes(p.stdout)
        stderr = self._decode_bytes(p.stderr)
        data = self._parse_json_from_stdout(stdout)
        success = (
            None
            if not data
            else bool(data.get("success")) if "success" in data else None
        )

        result = JarCallResult(
            returncode=p.returncode,
            command=cmd,
            stdout=stdout,
            stderr=stderr,
            data=data,
            success=success,
        )

        if check and p.returncode != 0:
            raise JarCallError(result)
        if check and data is None:
            raise RuntimeError(f"CLI stdout is not valid JSON: {stdout}")
        if check and success is False:
            raise JarCallError(result)

        return result

    # ---------- specialized methods ----------
    def send_text(
        self,
        *,
        conversation_id: str,
        conversation_short_id: int | str,
        content: str,
        is_group: bool = False,
        timeout_sec: Optional[int] = None,
        check: bool = True,
    ) -> JarCallResult:
        return self._call(
            "text",
            params={
                "conversationId": conversation_id,
                "conversationShortId": conversation_short_id,
                "content": content,
                "isGroup": is_group,
            },
            timeout_sec=timeout_sec,
            check=check,
        )

    def send_video_card(
        self,
        *,
        conversation_id: str,
        conversation_short_id: int | str,
        item_id: int | str,
        is_group: bool = False,
        timeout_sec: Optional[int] = None,
        check: bool = True,
    ) -> JarCallResult:
        return self._call(
            "video_card",
            params={
                "conversationId": conversation_id,
                "conversationShortId": conversation_short_id,
                "itemId": item_id,
                "isGroup": is_group,
            },
            timeout_sec=timeout_sec,
            check=check,
        )

    def send_dynamic_emoji(
        self,
        *,
        conversation_id: str,
        conversation_short_id: int | str,
        emoji_name: str,
        is_group: bool = False,
        timeout_sec: Optional[int] = None,
        check: bool = True,
    ) -> JarCallResult:
        return self._call(
            "dynamic_emoji",
            params={
                "conversationId": conversation_id,
                "conversationShortId": conversation_short_id,
                "emojiName": emoji_name,
                "isGroup": is_group,
            },
            timeout_sec=timeout_sec,
            check=check,
        )

    def send_image_upload(
        self,
        *,
        conversation_id: str,
        conversation_short_id: int | str,
        image_path: str | Path,
        is_group: bool = False,
        timeout_sec: Optional[int] = None,
        check: bool = True,
    ) -> JarCallResult:
        return self._call(
            "image_upload",
            params={
                "conversationId": conversation_id,
                "conversationShortId": conversation_short_id,
                "imagePath": str(image_path),
                "isGroup": is_group,
            },
            timeout_sec=timeout_sec,
            check=check,
        )

    def send_stranger_text(
        self,
        *,
        sec_uid: str,
        content: str,
        timeout_sec: Optional[int] = None,
        check: bool = True,
    ) -> JarCallResult:
        return self._call(
            "stranger_text",
            params={"secUid": sec_uid, "content": content},
            timeout_sec=timeout_sec,
            check=check,
        )


if __name__ == "__main__":
    pass
    # client = DouyinPmCliClient(
    #     session_id="",
    #     user_id="0",
    #     ms_token="your_ms_token",
    #     verify_fp="verify_xxx",
    #     fp="verify_xxx",
    #     uifid="your_uifid",
    #     # jar_path=None, java_path=None => auto detect
    # )

    # 使用 @property setter 动态更新
    # client.session_id = "new_session"
    # client.user_id = "new_user"
    # client.verify_fp = "verify_new"
    # client.fp = "verify_new"

    # result = client.send_video_card(
    #     conversation_id="",
    #     conversation_short_id=,
    #     item_id="7610001906357882166",
    #     is_group=False,
    # )

    # print(result.data)
    # print(result.stderr)
