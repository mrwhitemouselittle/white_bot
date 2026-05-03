import asyncio

from google import genai

from bot.logger import get_logger
from bot.settings import settings

logger = get_logger(__name__)

FOOD_PROMPT = """
请随机生成一道来自全球任意地区的美食，并给出一人份大致热量。

要求：
1. 每次尽量选择不同国家或地区的食物。
2. 用中文回答。
3. 热量必须是估算值，单位使用 kcal。
4. 不要输出 Markdown 表格。
5. 按下面格式输出：

今天吃：菜名
来自：国家/地区
热量：约 xxx kcal/份
简介：一句话说明这道食物的主要食材或特色
""".strip()


def _generate_food_recommendation_sync() -> str:
    logger.info("Requesting Gemini food recommendation with model=%s", settings.gemini_model)
    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=FOOD_PROMPT,
    )
    return (response.text or "").strip()


async def generate_food_recommendation() -> str:
    text = await asyncio.to_thread(_generate_food_recommendation_sync)

    if not text:
        logger.warning("Gemini returned an empty food recommendation.")
        raise RuntimeError("Gemini returned an empty response.")

    logger.info("Gemini food recommendation generated.")
    return text
