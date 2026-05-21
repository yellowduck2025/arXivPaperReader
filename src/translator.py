"""统一翻译接口 — 支持 LLM / Google / Bing / DeepL / 百度 / 腾讯 / 自定义."""

from __future__ import annotations

import hashlib
import hmac
import random
import time as _time
from dataclasses import dataclass, field
from typing import Literal

from openai import OpenAI

TranslationBackend = Literal["llm", "google", "bing", "deepl", "baidu", "tencent", "custom"]


@dataclass
class TranslateConfig:
    backend: TranslationBackend = "google"
    # LLM
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "deepseek-chat"
    # Bing
    bing_api_key: str = ""
    bing_region: str = "global"
    # DeepL
    deepl_api_key: str = ""
    # 百度
    baidu_appid: str = ""
    baidu_secret_key: str = ""
    # 腾讯
    tencent_secret_id: str = ""
    tencent_secret_key: str = ""
    tencent_region: str = "ap-guangzhou"
    # Custom
    custom_url: str = ""
    custom_api_key: str = ""


def translate_text(text: str, config: TranslateConfig) -> str:
    """将英文文本翻译为简体中文。"""
    backend_map = {
        "llm": _translate_llm,
        "google": _translate_google,
        "bing": _translate_bing,
        "deepl": _translate_deepl,
        "baidu": _translate_baidu,
        "tencent": _translate_tencent,
        "custom": _translate_custom,
    }
    fn = backend_map.get(config.backend)
    if fn is None:
        raise ValueError(f"未知翻译后端: {config.backend}")
    return fn(text, config)


# ── LLM ──────────────────────────────────────────────────────────

TRANSLATE_SYSTEM_PROMPT = (
    "You are a professional academic translator. "
    "Translate the following English academic text into Simplified Chinese (简体中文). "
    "Rules:\n"
    "- Use precise academic terminology in Chinese\n"
    "- Preserve the original meaning exactly\n"
    "- Output ONLY the Chinese translation, no explanations, no notes\n"
    "- Keep technical terms without standard Chinese translation in English"
)


def _translate_llm(text: str, config: TranslateConfig) -> str:
    client = OpenAI(api_key=config.llm_api_key, base_url=config.llm_base_url)
    resp = client.chat.completions.create(
        model=config.llm_model,
        messages=[
            {"role": "system", "content": TRANSLATE_SYSTEM_PROMPT},
            {"role": "user", "content": f"Translate to Chinese:\n\n{text}"},
        ],
        temperature=0.0,
        max_tokens=2048,
    )
    content = resp.choices[0].message.content
    return content.strip() if content else text


# ── Google ───────────────────────────────────────────────────────

def _translate_google(text: str, config: TranslateConfig) -> str:
    from deep_translator import GoogleTranslator
    return GoogleTranslator(source="auto", target="zh-CN").translate(text)


# ── Bing / Microsoft Translator ──────────────────────────────────

def _translate_bing(text: str, config: TranslateConfig) -> str:
    import requests

    if not config.bing_api_key:
        raise ValueError("Bing API Key 未配置，请在设置中填写")

    endpoint = "https://api.cognitive.microsofttranslator.com/translate"
    params = {"api-version": "3.0", "to": "zh-Hans"}
    headers = {
        "Ocp-Apim-Subscription-Key": config.bing_api_key,
        "Ocp-Apim-Subscription-Region": config.bing_region or "global",
        "Content-Type": "application/json",
    }
    body = [{"Text": text}]
    resp = requests.post(endpoint, params=params, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    return result[0]["translations"][0]["text"]


# ── DeepL ────────────────────────────────────────────────────────

def _translate_deepl(text: str, config: TranslateConfig) -> str:
    import requests

    if not config.deepl_api_key:
        raise ValueError("DeepL API Key 未配置，请在设置中填写")

    api_url = (
        "https://api-free.deepl.com/v2/translate"
        if config.deepl_api_key.endswith(":fx")
        else "https://api.deepl.com/v2/translate"
    )
    resp = requests.post(
        api_url,
        data={"text": text, "target_lang": "ZH", "auth_key": config.deepl_api_key},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["translations"][0]["text"]


# ── 百度翻译 ─────────────────────────────────────────────────────

def _translate_baidu(text: str, config: TranslateConfig) -> str:
    import requests

    if not config.baidu_appid or not config.baidu_secret_key:
        raise ValueError("百度翻译 APPID / SecretKey 未配置，请在设置中填写")

    salt = str(random.randint(32768, 65536))
    sign_str = config.baidu_appid + text + salt + config.baidu_secret_key
    sign = hashlib.md5(sign_str.encode("utf-8")).hexdigest()

    resp = requests.get(
        "https://fanyi-api.baidu.com/api/trans/vip/translate",
        params={
            "q": text,
            "from": "en",
            "to": "zh",
            "appid": config.baidu_appid,
            "salt": salt,
            "sign": sign,
        },
        timeout=30,
    )
    result = resp.json()
    if "error_code" in result and result["error_code"]:
        raise RuntimeError(f"百度翻译错误: {result.get('error_msg', result['error_code'])}")
    return result["trans_result"][0]["dst"]


# ── 腾讯翻译 (TMT) ───────────────────────────────────────────────

def _tc3_sign(
    secret_id: str,
    secret_key: str,
    service: str,
    host: str,
    action: str,
    payload: str,
    region: str,
) -> dict[str, str]:
    """TC3-HMAC-SHA256 签名，返回请求头字典。"""
    algorithm = "TC3-HMAC-SHA256"
    timestamp = int(_time.time())
    date = _time.strftime("%Y-%m-%d", _time.gmtime(timestamp))

    # Step 1: Canonical Request
    canonical_headers = f"content-type:application/json; charset=utf-8\nhost:{host}\nx-tc-action:{action.lower()}\n"
    signed_headers = "content-type;host;x-tc-action"
    hashed_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = (
        f"POST\n/\n\n{canonical_headers}\n{signed_headers}\n{hashed_payload}"
    )

    # Step 2: String to Sign
    credential_scope = f"{date}/{service}/tc3_request"
    hashed_canonical = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = f"{algorithm}\n{timestamp}\n{credential_scope}\n{hashed_canonical}"

    # Step 3: Signature
    def _sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    secret_date = _sign(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _sign(secret_date, service)
    secret_signing = _sign(secret_service, "tc3_request")
    signature = hmac.new(
        secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    # Step 4: Authorization
    authorization = (
        f"{algorithm} Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    return {
        "Authorization": authorization,
        "Content-Type": "application/json; charset=utf-8",
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": "2018-03-21",
        "X-TC-Region": region,
    }


def _translate_tencent(text: str, config: TranslateConfig) -> str:
    import requests

    if not config.tencent_secret_id or not config.tencent_secret_key:
        raise ValueError("腾讯翻译 SecretId / SecretKey 未配置，请在设置中填写")

    import json

    host = "tmt.tencentcloudapi.com"
    payload = json.dumps({
        "SourceText": text,
        "Source": "en",
        "Target": "zh",
        "ProjectId": 0,
    })

    headers = _tc3_sign(
        secret_id=config.tencent_secret_id,
        secret_key=config.tencent_secret_key,
        service="tmt",
        host=host,
        action="TextTranslate",
        payload=payload,
        region=config.tencent_region or "ap-guangzhou",
    )

    resp = requests.post(
        f"https://{host}",
        data=payload,
        headers=headers,
        timeout=30,
    )
    result = resp.json()
    if "Response" in result and "Error" in result["Response"]:
        raise RuntimeError(
            f"腾讯翻译错误: {result['Response']['Error'].get('Message', result['Response']['Error'].get('Code', ''))}"
        )
    return result["Response"]["TargetText"]


# ── Custom API ────────────────────────────────────────────────────

def _translate_custom(text: str, config: TranslateConfig) -> str:
    import requests

    if not config.custom_url:
        raise ValueError("自定义翻译 URL 未配置，请在设置中填写")

    body: dict = {"text": text, "sourceLang": "en", "targetLang": "zh-CN"}
    if config.custom_api_key:
        body["apiKey"] = config.custom_api_key

    resp = requests.post(
        config.custom_url,
        json=body,
        headers={"Content-Type": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()
    result = resp.json()

    # 尝试从常见字段提取
    if isinstance(result, dict):
        for field in ("data", "translation", "translatedText", "text", "result"):
            if field in result and isinstance(result[field], str) and result[field]:
                return result[field]
        if "translations" in result and isinstance(result["translations"], list):
            return result["translations"][0].get("text", "")
    if isinstance(result, str):
        return result
    return str(result)
