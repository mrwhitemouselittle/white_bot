import asyncio
import html
import io
import json
import posixpath
import random
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from PIL import Image, ImageOps

from bot.logger import get_logger

logger = get_logger(__name__)

REPO_OWNER = "Anduin2017"
REPO_NAME = "HowToCook"
REPO_BRANCH = "master"
TREE_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/git/trees/{REPO_BRANCH}?recursive=1"
RAW_BASE_URL = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{REPO_BRANCH}"
MEDIA_BASE_URL = f"https://media.githubusercontent.com/media/{REPO_OWNER}/{REPO_NAME}/{REPO_BRANCH}"
HTML_BASE_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/blob/{REPO_BRANCH}"
TREE_CACHE_SECONDS = 3600
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
EXCLUDED_RECIPE_CATEGORIES = {"condiment", "drink"}

_tree_cache: tuple[float, list[dict[str, Any]]] | None = None


@dataclass(frozen=True)
class FoodRecommendation:
    title: str
    intro: str
    difficulty: str
    calories: str
    recipe_url: str
    image_url: str | None

    def to_message(self) -> str:
        return (
            f"今天吃：{self.title}\n"
            f"简介：{self.intro}\n"
            f"卡路里：{self.calories}\n"
            f"做法：{self.recipe_url}"
        )

    def to_html_message(self) -> str:
        calories = _format_calories_html(self.calories)
        return (
            f"<b>今天吃</b>\n{html.escape(self.title)}\n\n"
            f"<b>简介</b>\n<blockquote>{html.escape(self.intro)}</blockquote>\n\n"
            f"<b>预估烹饪难度</b>\n{html.escape(self.difficulty)}\n\n"
            f"<b>卡路里</b>\n{calories}\n\n"
            f'<a href="{html.escape(self.recipe_url)}">查看完整做法</a>'
        )


async def generate_food_recommendation() -> FoodRecommendation:
    return await asyncio.to_thread(_generate_food_recommendation_sync)


async def fetch_recipe_image(image_url: str) -> io.BytesIO:
    return await asyncio.to_thread(_fetch_image_sync, image_url)


def _generate_food_recommendation_sync() -> FoodRecommendation:
    tree = _get_repo_tree()
    recipes = _recipe_paths(tree)
    if not recipes:
        raise RuntimeError("No HowToCook recipes found.")

    recipe_path = random.choice(recipes)
    markdown = _fetch_text(_raw_url(recipe_path))
    recommendation = _parse_recipe(recipe_path, markdown, tree)
    logger.info("HowToCook recipe selected title=%s path=%s", recommendation.title, recipe_path)
    return recommendation


def _get_repo_tree() -> list[dict[str, Any]]:
    global _tree_cache

    now = time.time()
    if _tree_cache is not None:
        cached_at, cached_tree = _tree_cache
        if now - cached_at < TREE_CACHE_SECONDS:
            return cached_tree

    data = json.loads(_fetch_text(TREE_URL))
    tree = data.get("tree", [])
    if not isinstance(tree, list):
        raise RuntimeError("GitHub tree response is invalid.")

    _tree_cache = (now, tree)
    return tree


def _recipe_paths(tree: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for item in tree:
        path = item.get("path")
        if (
            isinstance(path, str)
            and item.get("type") == "blob"
            and path.startswith("dishes/")
            and path.endswith(".md")
            and path.count("/") >= 2
            and _recipe_category(path) not in EXCLUDED_RECIPE_CATEGORIES
        ):
            paths.append(path)

    return sorted(paths)


def _parse_recipe(recipe_path: str, markdown: str, tree: list[dict[str, Any]]) -> FoodRecommendation:
    title = _extract_title(recipe_path, markdown)
    intro = _extract_intro(markdown)
    difficulty = _extract_difficulty(markdown)
    calories = _extract_calories(markdown)
    image_url = _extract_image_url(recipe_path, markdown, tree)

    return FoodRecommendation(
        title=title,
        intro=intro,
        difficulty=difficulty,
        calories=calories,
        recipe_url=_html_url(recipe_path),
        image_url=image_url,
    )


def _recipe_category(path: str) -> str:
    parts = path.split("/")
    return parts[1] if len(parts) > 1 else ""


def _extract_title(recipe_path: str, markdown: str) -> str:
    for line in markdown.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return _clean_title(match.group(1))

    stem = posixpath.splitext(posixpath.basename(recipe_path))[0]
    return _clean_title(stem) or "未知菜谱"


def _extract_intro(markdown: str) -> str:
    lines = markdown.splitlines()
    title_seen = False
    paragraph: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not title_seen:
            if stripped.startswith("# "):
                title_seen = True
            continue

        if stripped.startswith("## "):
            break
        if not stripped or stripped.startswith("!") or stripped.startswith("["):
            continue
        if stripped.startswith("#"):
            continue
        paragraph.append(stripped)

    if paragraph:
        return _truncate(_clean_intro(" ".join(paragraph)), 120)

    ingredients = _extract_ingredients(markdown)
    if ingredients:
        return _truncate(f"主要食材：{'、'.join(ingredients)}", 120)

    return "来自 HowToCook 的开源菜谱。"


def _extract_ingredients(markdown: str) -> list[str]:
    in_section = False
    ingredients: list[str] = []

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = "原料" in stripped or "工具" in stripped
            continue
        if in_section and stripped.startswith("## "):
            break
        if not in_section:
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            item = re.sub(r"^[-*]\s+", "", stripped)
            item = re.split(r"[：:，,（(]", item, maxsplit=1)[0].strip()
            if item:
                ingredients.append(item)
        if len(ingredients) >= 5:
            break

    return ingredients


def _extract_calories(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        match = re.match(r"^(?:预估)?(?:热量|卡路里|calories?)\s*[：:]\s*(.+)$", stripped, re.IGNORECASE)
        if match:
            return _truncate(match.group(1).strip(), 80)

    for line in markdown.splitlines():
        stripped = line.strip()
        if re.search(r"(kcal|千卡|大卡)", stripped, re.IGNORECASE):
            text = stripped.lstrip("-* ")
            return _truncate(text, 80)

    return "仓库未提供"


def _extract_difficulty(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        match = re.match(r"^(?:预估)?(?:烹饪)?难度\s*[：:]\s*(.+)$", stripped)
        if match:
            return _truncate(match.group(1).strip(), 40)

    return "仓库未提供"


def _extract_image_url(recipe_path: str, markdown: str, tree: list[dict[str, Any]]) -> str | None:
    recipe_dir = posixpath.dirname(recipe_path)
    directory_image_url = _directory_image_url(recipe_dir, tree)
    if directory_image_url:
        return directory_image_url

    for match in re.finditer(r"!\[[^\]]*]\(([^)]+)\)", markdown):
        image_ref = match.group(1).strip().split()[0]
        if image_ref:
            return _resolve_asset_url(recipe_dir, image_ref)

    return None


def _directory_image_url(recipe_dir: str, tree: list[dict[str, Any]]) -> str | None:
    directory_images = [
        item.get("path")
        for item in tree
        if isinstance(item.get("path"), str)
        and item.get("type") == "blob"
        and posixpath.dirname(item["path"]) == recipe_dir
        and item["path"].lower().endswith(IMAGE_EXTENSIONS)
    ]
    if not directory_images:
        return None

    return _media_url(sorted(directory_images)[0])


def _resolve_asset_url(recipe_dir: str, image_ref: str) -> str:
    if image_ref.startswith(("http://", "https://")):
        return _normalize_image_url(image_ref)

    normalized_path = posixpath.normpath(posixpath.join(recipe_dir, image_ref.lstrip("/")))
    return _media_url(normalized_path)


def _normalize_image_url(image_url: str) -> str:
    raw_prefix = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{REPO_BRANCH}/"
    if image_url.startswith(raw_prefix):
        return f"{MEDIA_BASE_URL}/{image_url.removeprefix(raw_prefix)}"

    return image_url


def _fetch_text(url: str) -> str:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "white0456-bot",
        },
    )
    with urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8")


def _fetch_image_sync(url: str) -> io.BytesIO:
    request = Request(url, headers={"User-Agent": "white0456-bot"})
    with urlopen(request, timeout=15) as response:
        raw_image = io.BytesIO(response.read())

    with Image.open(raw_image) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGBA")
            background = Image.new("RGBA", image.size, (255, 255, 255, 255))
            background.alpha_composite(image)
            image = background.convert("RGB")
        else:
            image = image.convert("RGB")

        output = io.BytesIO()
        image.save(output, format="JPEG", quality=88, optimize=True)
        output.name = "recipe.jpg"
        output.seek(0)
        return output


def _raw_url(path: str) -> str:
    return f"{RAW_BASE_URL}/{quote(path, safe='/')}"


def _media_url(path: str) -> str:
    return f"{MEDIA_BASE_URL}/{quote(path, safe='/')}"


def _html_url(path: str) -> str:
    return f"{HTML_BASE_URL}/{quote(path, safe='/')}"


def _truncate(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def _clean_title(value: str) -> str:
    return re.sub(r"(的)?做法$", "", value.strip()).strip()


def _clean_intro(value: str) -> str:
    value = re.split(r"\s*预估(?:烹饪难度|卡路里|热量)", value, maxsplit=1)[0]
    return value.strip(" 。；;")


def _format_calories_html(value: str) -> str:
    escaped = html.escape(value)
    match = re.search(r"(\d+(?:\.\d+)?)", escaped)
    if not match:
        return escaped

    number = match.group(1)
    formatted_number = f"<b><i><u>{number}</u></i></b>"
    return escaped[: match.start(1)] + formatted_number + escaped[match.end(1) :]
