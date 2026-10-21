# Lab overlay: force English UI (runs after LocaleMiddleware).
LANGUAGE_CODE = 'en'
LANGUAGES = (
    ('en', 'English'),
)

_force_en = 'lab_force_en.ForceEnglishMiddleware'
try:
    if _force_en not in MIDDLEWARE_CLASSES:
        MIDDLEWARE_CLASSES = MIDDLEWARE_CLASSES + (_force_en,)
except NameError:
    pass
