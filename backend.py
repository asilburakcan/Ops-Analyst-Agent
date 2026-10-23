"""The only file that talks to AWS.

Data : S3 (Parquet) + Glue Data Catalog, queried with Athena
LLM  : Bedrock
Credentials come from the EC2 instance role (or `aws configure` on a laptop). No keys in code.
"""
import os

import awswrangler as wr
import boto3
from dotenv import load_dotenv

load_dotenv()

REGION = os.getenv("AWS_REGION", "eu-central-1")
BUCKET = os.environ["S3_BUCKET"]
DATABASE = os.getenv("GLUE_DATABASE", "last_mile")
SQL_MODEL = os.getenv("SQL_MODEL", "eu.amazon.nova-pro-v1:0")
ANALYST_MODEL = os.getenv("ANALYST_MODEL", "eu.amazon.nova-2-lite-v1:0")
TABLES = ["lm_routes", "lm_stops", "lm_packages"]  # source data; result tables are added by the jobs

session = boto3.Session(region_name=REGION)
bedrock = session.client("bedrock-runtime")


def query(sql, big=False):
    """Run Athena SQL, return a DataFrame. big=True lets Athena write Parquet first (fast for large results)."""
    return wr.athena.read_sql_query(sql, database=DATABASE, ctas_approach=big,
                                    s3_output=f"s3://{BUCKET}/athena-results/", boto3_session=session)


def save(df, table, mode="append"):
    """Write rows as Parquet to s3://BUCKET/table/ and register the table in Glue."""
    wr.s3.to_parquet(df, f"s3://{BUCKET}/{table}/", dataset=True, mode=mode,
                     database=DATABASE, table=table, boto3_session=session)


def exists(table):
    return wr.catalog.does_table_exist(DATABASE, table, boto3_session=session)


def llm(model, messages):
    """One Bedrock chat call. messages: [{"role": "system" | "user" | "assistant", "content": str}]"""
    r = bedrock.converse(
        modelId=model,
        system=[{"text": m["content"]} for m in messages if m["role"] == "system"],
        messages=[{"role": m["role"], "content": [{"text": m["content"]}]}
                  for m in messages if m["role"] != "system"],
        inferenceConfig={"temperature": 0, "maxTokens": 1500})
    return "".join(block.get("text", "") for block in r["output"]["message"]["content"])
