"""Create Parali Mitra DynamoDB tables with on-demand capacity and TTL."""

import os
import sys
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

region = os.getenv("AWS_REGION", "ap-south-1")
aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
aws_session_token = os.getenv("AWS_SESSION_TOKEN")

kwargs = {"region_name": region}
if aws_access_key and aws_secret_key:
    kwargs["aws_access_key_id"] = aws_access_key
    kwargs["aws_secret_access_key"] = aws_secret_key
    if aws_session_token:
        kwargs["aws_session_token"] = aws_session_token

dynamodb = boto3.client("dynamodb", **kwargs)

tables = [
    {
        "TableName": "ParaliMitra_Machines",
        "KeySchema": [{"AttributeName": "machine_id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "machine_id", "AttributeType": "S"}],
    },
    {
        "TableName": "ParaliMitra_Buyers",
        "KeySchema": [{"AttributeName": "buyer_id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "buyer_id", "AttributeType": "S"}],
    },
    {
        "TableName": "ParaliMitra_Bookings",
        "KeySchema": [{"AttributeName": "booking_id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "booking_id", "AttributeType": "S"}],
    },
    {
        "TableName": "ParaliMitra_Sessions",
        "KeySchema": [{"AttributeName": "chat_id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "chat_id", "AttributeType": "N"}],
    },
    {
        "TableName": "ParaliMitra_Hotspots",
        "KeySchema": [{"AttributeName": "grid_key", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "grid_key", "AttributeType": "S"}],
        "TTL": "ttl",
    },
    {
        "TableName": "ParaliMitra_ProcessedUpdates",
        "KeySchema": [{"AttributeName": "update_id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "update_id", "AttributeType": "S"}],
        "TTL": "ttl",
    },
]


def create_all_tables() -> None:
    print(f"Connecting to DynamoDB in region: {region}...")
    try:
        existing_tables = dynamodb.list_tables().get("TableNames", [])
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        print(f"\n❌ AWS DynamoDB Access Error ({error_code}):")
        print(f"   {error_msg}\n")
        if "service control policy" in error_msg.lower() or "explicit deny" in error_msg.lower():
            print("💡 TIP: Your AWS Student/Learner account has an active Service Control Policy (SCP).")
            print("   1. Check if your student account is restricted to a specific region (e.g. us-east-1 or ap-south-1).")
            print("   2. You can set DATABASE_MODE=local in your .env to run 100% of the project locally without DynamoDB.")
        sys.exit(1)

    for table_info in tables:
        name = table_info["TableName"]
        if name in existing_tables:
            print(f"✓ Table '{name}' already exists. Skipping.")
            continue

        print(f"Creating table '{name}'...")
        try:
            dynamodb.create_table(
                TableName=name,
                KeySchema=table_info["KeySchema"],
                AttributeDefinitions=table_info["AttributeDefinitions"],
                BillingMode="PAY_PER_REQUEST",
            )

            # Wait for table creation before enabling TTL if specified
            if "TTL" in table_info:
                waiter = dynamodb.get_waiter("table_exists")
                waiter.wait(TableName=name)
                dynamodb.update_time_to_live(
                    TableName=name,
                    TimeToLiveSpecification={
                        "Enabled": True,
                        "AttributeName": table_info["TTL"],
                    },
                )
                print(f"  ✓ TTL enabled on '{table_info['TTL']}' for table '{name}'.")
            else:
                print(f"  ✓ Table '{name}' created.")
        except ClientError as e:
            print(f"  ❌ Failed to create table '{name}': {e}")

    print("\n✅ Table creation process finished.")


if __name__ == "__main__":
    create_all_tables()