# ai_client.py
import json
import logging
import google.generativeai as genai

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────
DEFAULT_GEMINI_API_KEY = "AIzaSyBO3VlytGpWr5YloX-4ElbBT32bE7IW7Wk"

DEFAULT_PROMPT_TEMPLATE = (
    "Выполни следующий алгоритм действий\n"
    "Проанализируй вложенный файл-условие и пользовательский запрос:\n"
    "{user_query}\n"
    "Выдели из анализа только грубую структуру директорий и названия файлов\n"
    "После уточни нейминг директорий/файлов и добавь пустые файлы по необходимости"
)
# ──────────────────────────────────────────────────────────


class GeminiClient:
    """
    Клиент для взаимодействия с Google Gemini API.
    Возвращает предложенную структуру каталогов в формате JSON.
    """

    def __init__(self, api_key: str | None, prompt_template: str | None = None) -> None:
        # 1) Ключ
        self.api_key: str = (
            api_key
            if api_key
            and not api_key.startswith("YOUR_GEMINI_API_KEY")
            and api_key != "DUMMY_KEY"
            else DEFAULT_GEMINI_API_KEY
        )

        # 2) Шаблон промпта
        self.prompt_template: str = (
            prompt_template.strip() if prompt_template else DEFAULT_PROMPT_TEMPLATE
        )

        # 3) Конфигурация модели
        try:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(
                model_name="gemini-2.0-pro",
                generation_config=genai.types.GenerationConfig(temperature=0.6),
                safety_settings=[
                    {
                        "category": "HARM_CATEGORY_HARASSMENT",
                        "threshold": "BLOCK_MEDIUM_AND_ABOVE",
                    },
                    {
                        "category": "HARM_CATEGORY_HATE_SPEECH",
                        "threshold": "BLOCK_MEDIUM_AND_ABOVE",
                    },
                    {
                        "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                        "threshold": "BLOCK_MEDIUM_AND_ABOVE",
                    },
                    {
                        "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                        "threshold": "BLOCK_MEDIUM_AND_ABOVE",
                    },
                ],
            )
            logger.info("GeminiClient: модель инициализирована.")
        except Exception as exc:
            logger.error("GeminiClient: ошибка инициализации модели — %s", exc, exc_info=True)
            self.model = None  # AI-функции будут недоступны

    # ──────────────────────────────────────────────────────────

    def _build_prompt(self, file_content: str, user_query: str) -> str:
        """Возвращает сформированный промпт для LLM."""
        # Ограничиваем объём контента (≈32 K символов ≈ 8 K токенов)
        MAX_CHARS = 32000
        if len(file_content) > MAX_CHARS:
            logger.warning("Содержимое файла >32 K — усечено для промпта.")
            file_content = file_content[:MAX_CHARS] + "\n[...CONTENT TRUNCATED...]"

        return self.prompt_template.format(user_query=user_query, file_content=file_content)

    # ──────────────────────────────────────────────────────────

    def get_structure_suggestion(
        self, file_content_string: str, user_query_string: str = ""
    ) -> dict | None:
        """Запрашивает у Gemini предложенную структуру."""
        if not self.model:
            logger.error("GeminiClient: модель не инициализирована.")
            return None

        prompt = self._build_prompt(file_content_string, user_query_string)
        logger.debug("Gemini prompt (первые 400 симв.): %s...", prompt[:400])

        # Для разработческой офф-лайн-отладки (оставлено на случай):
        if self.api_key.startswith("DUMMY_KEY_FOR_"):
            logger.info("GeminiClient: режим mock-ответа (%s).", self.api_key)
            if self.api_key == "DUMMY_KEY_FOR_SUCCESS_MOCK":
                return {
                    "name": "AISuggestedProject",
                    "type": "directory",
                    "children": [
                        {
                            "name": "src",
                            "type": "directory",
                            "children": [{"name": "main.py", "type": "file"}],
                        },
                        {"name": "README.md", "type": "file"},
                    ],
                }
            if self.api_key == "DUMMY_KEY_FOR_JSON_ERROR_MOCK":
                return None

        # ─── Реальный вызов API ───────────────────────────
        try:
            response = self.model.generate_content(prompt)
            if hasattr(response, "text"):
                response_text = response.text
            else:
                # Gemini v1/v2 иногда возвращают parts
                response_text = "".join(part.text for part in response.parts)

            if not response_text:
                logger.warning("GeminiClient: пустой ответ от AI.")
                return None

            # Удаляем возможные Markdown-ограждения ```
            response_text = response_text.strip().removeprefix("```json").removesuffix("```")
            suggestion = json.loads(response_text)

            # Базовая валидация
            if not isinstance(suggestion, dict) or "name" not in suggestion or "type" not in suggestion:
                logger.error("GeminiClient: ответ не соответствует ожидаемому формату JSON.")
                return None

            logger.info("GeminiClient: структура получена и распарсена.")
            return suggestion

        except json.JSONDecodeError as exc:
            logger.error("GeminiClient: ошибка JSON-декодирования — %s", exc, exc_info=True)
        except genai.types.BlockedPromptException as exc:
            logger.error("GeminiClient: запрос заблокирован политиками — %s", exc, exc_info=True)
        except Exception as exc:
            logger.error("GeminiClient: общая ошибка при вызове API — %s", exc, exc_info=True)

        return None
