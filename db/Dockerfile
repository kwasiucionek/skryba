# Obraz bazy: pgvector + polski słownik hunspell dla pełnotekstowego
# wyszukiwania ze stemmingiem (konfiguracja `polish`).
FROM pgvector/pgvector:pg16

# Katalog słowników wyszukiwania Postgresa (stała ścieżka dla pg16).
ENV TS_DATA=/usr/share/postgresql/16/tsearch_data

# Instalujemy słownik hunspell-pl, konwertujemy ISO-8859-2 -> UTF-8
# (serwer pracuje w UTF-8) i poprawiamy deklarację SET w pliku affix.
# iconv i sed są w obrazie bazowym (glibc/coreutils).
RUN apt-get update \
    && apt-get install -y --no-install-recommends hunspell-pl \
    && iconv -f ISO-8859-2 -t UTF-8 /usr/share/hunspell/pl_PL.aff \
         | sed 's/^SET ISO8859-2/SET UTF-8/' > "$TS_DATA/polish.affix" \
    && iconv -f ISO-8859-2 -t UTF-8 /usr/share/hunspell/pl_PL.dic > "$TS_DATA/polish.dict" \
    && apt-get purge -y hunspell-pl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Lista stopwords (bundlowana w repo).
COPY tsearch/polish.stop /usr/share/postgresql/16/tsearch_data/polish.stop
