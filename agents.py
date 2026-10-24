"""Two agents answer last-mile questions straight from the data in Athena.

1) SQL agent     : question -> Athena SQL, repairs its own failed queries
2) Analyst agent : result -> finding, root-cause hypothesis, automation idea

python agents.py "Which station has the highest failed delivery rate?"
"""
import functools
import json
import re
import sys
import time
from pathlib import Path

import backend as b

MAX_REPAIRS = 2
FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|merge|unload|msck|call)\b", re.I)

# The glossary in DATA_DICTIONARY.md is the shared vocabulary of both agents and the docs.
_DOC = (Path(__file__).parent / "DATA_DICTIONARY.md").read_text(encoding="utf-8")
GLOSSARY = _DOC.split("## Glossary", 1)[1].split("\n## ", 1)[0].strip()

ANALYST_PROMPT = f"""You are a last-mile operations analyst agent. You get a business question and the data result.
Terms (use them exactly; packages, stops and routes are different units):
{GLOSSARY}
Rules for root_cause_hypothesis:
- Name a cause only if the result itself compares groups (e.g. fail rate with vs without a time window).
- If the result only lists values (a top station, a maximum, a count), it shows no cause: write
  "Not shown by this result; check <the comparison that would test it>".
- A result can combine separate answers (e.g. a station and a package size); never link them as cause and effect.
Return JSON only: {{"finding": "max 30 words, with key numbers and correct units",
"root_cause_hypothesis": "max 25 words, only from fields in the data; if the data cannot explain it, name the check that would",
"automation_idea": "max 25 words: a manual process this finding suggests automating"}}"""


@functools.cache
def sql_prompt():
    tables = ", ".join(f"'{t}'" for t in b.TABLES)
    cols = b.query("SELECT table_name, column_name, data_type FROM information_schema.columns "
                   f"WHERE table_schema = '{b.DATABASE}' AND table_name IN ({tables}) ORDER BY table_name, ordinal_position")
    schema = "\n".join(f"Table {t}(" + ", ".join(f"{r.column_name} {r.data_type}" for r in g.itertuples()) + ")"
                       for t, g in cols.groupby("table_name"))
    return f"""You are a SQL analyst agent. Write ONE read-only query that answers the user's question.
Dialect: Amazon Athena (Trino SQL). Round with round(x, 2). Never use :: casts.
{schema}
Terms:
{GLOSSARY}
Percentages are 0-100. Round averages, sums and percentages to 2 decimals.
Return only the columns needed. Output only the SQL."""


def chat(model, messages):
    for attempt in range(3):
        try:
            return re.sub(r"<think>.*?</think>", "", b.llm(model, messages), flags=re.DOTALL)
        except Exception as e:
            print(f"  LLM error ({model}, try {attempt + 1}): {str(e)[:120]}")
            time.sleep(10 * (attempt + 1))
    return ""


def run_sql(sql):
    if not re.match(r"^\s*(select|with)\b", sql, re.I) or FORBIDDEN.search(sql):
        raise ValueError("only read-only SELECT queries are allowed")
    return b.query(sql)


def write_sql(question):
    """SQL agent: returns (sql, DataFrame or None, repairs used)."""
    sql, err = "", None
    for repairs in range(MAX_REPAIRS + 1):
        msgs = [{"role": "system", "content": sql_prompt()}, {"role": "user", "content": question}]
        if err:  # self-repair: show the agent its own error
            msgs += [{"role": "assistant", "content": sql or "(empty)"},
                     {"role": "user", "content": f"That query failed: {err}\nFix it. Output only the SQL."}]
        txt = chat(b.SQL_MODEL, msgs)
        m = re.search(r"```(?:sql)?\s*(.*?)```", txt, re.DOTALL | re.I)
        sql = (m.group(1) if m else txt).strip().rstrip(";")
        try:
            df = run_sql(sql)
            if df.empty:  # an empty answer is almost always a wrong filter or join: repair it like an error
                raise ValueError("the query returned no rows; a filter or join is probably wrong")
            return sql, df, repairs
        except Exception as e:
            err = str(e).split("\n")[0][:200]
    return sql, None, MAX_REPAIRS


def analyze(question, result):
    """Analyst agent: any JSON-able result -> {finding, root_cause_hypothesis, automation_idea}."""
    txt = chat(b.ANALYST_MODEL, [{"role": "system", "content": ANALYST_PROMPT},
                                 {"role": "user", "content": json.dumps({"question": question, "result": result}, default=str)}])
    try:
        return json.loads(re.search(r"\{.*\}", txt, re.DOTALL).group(0))
    except Exception:
        return {}


def ask(question):
    sql, df, repairs = write_sql(question)
    analysis = analyze(question, df.head(20).to_dict("records")) if df is not None else {}
    return {"sql": sql, "df": df, "repairs": repairs, "analysis": analysis}


if __name__ == "__main__":
    r = ask(" ".join(sys.argv[1:]) or "What percentage of packages were not delivered?")
    print("\nSQL:", r["sql"], "\n")
    if r["df"] is not None:
        print(r["df"].head(20).to_string(index=False))
    print("\n", json.dumps(r["analysis"], indent=2))
