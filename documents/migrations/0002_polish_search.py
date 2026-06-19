"""Konfiguracja pełnotekstowego wyszukiwania dla języka polskiego.

Tworzy słownik ispell na bazie hunspell-pl i konfigurację `polish`
z lematyzacją form fleksyjnych. Słownik (pliki polish.affix/.dict/.stop)
dostarcza obraz bazy `db/Dockerfile`.

Blok jest idempotentny (pomija, gdy `polish` już istnieje) i tolerancyjny
— na zwykłym Postgresie bez plików słownika migracja nie zawiedzie,
a wyszukiwanie zostaje przy konfiguracji `simple`.
"""

from django.db import migrations

CREATE_POLISH = r"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'polish') THEN
        BEGIN
            CREATE TEXT SEARCH DICTIONARY polish_hunspell (
                TEMPLATE  = ispell,
                DictFile  = polish,
                AffFile   = polish,
                StopWords = polish
            );
            CREATE TEXT SEARCH CONFIGURATION polish (COPY = simple);
            ALTER TEXT SEARCH CONFIGURATION polish
                ALTER MAPPING FOR
                    asciiword, word, hword, hword_part, asciihword, hword_asciipart
                WITH polish_hunspell, simple;
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE
                'Pominięto konfigurację FTS polish (brak słownika hunspell?): %',
                SQLERRM;
        END;
    END IF;
END $$;
"""

DROP_POLISH = """
DROP TEXT SEARCH CONFIGURATION IF EXISTS polish CASCADE;
DROP TEXT SEARCH DICTIONARY IF EXISTS polish_hunspell CASCADE;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_POLISH, reverse_sql=DROP_POLISH),
    ]
