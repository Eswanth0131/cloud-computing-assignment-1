import json
import os
import uuid
import boto3
from datetime import datetime, timezone

lex = boto3.client("lexv2-runtime", region_name="us-east-1")

BOT_ID = os.environ.get("LEX_BOT_ID", "WUOBWOSFGY")
BOT_ALIAS_ID = os.environ.get("LEX_BOT_ALIAS_ID", "TSTALIASID")
LOCALE_ID = os.environ.get("LEX_LOCALE_ID", "en_US")

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
    "Access-Control-Allow-Methods": "OPTIONS,POST"
}


def api_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": HEADERS,
        "body": json.dumps(body)
    }


def chatbot_message(text):
    return {
        "type": "unstructured",
        "unstructured": {
            "id": str(uuid.uuid4()),
            "text": text,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    }


def lambda_handler(event, context):
    print("LF0 EVENT:", json.dumps(event))

    if event.get("httpMethod") == "OPTIONS":
        return api_response(200, {})

    try:
        body = event.get("body", {})

        if isinstance(body, str):
            body = json.loads(body)

        messages = body.get("messages", [])

        if not messages:
            return api_response(400, {
                "error": "No messages provided."
            })

        user_message = messages[-1].get("unstructured", {})

        text = user_message.get("text", "").strip()

        if not text:
            return api_response(400, {
                "error": "Message text cannot be empty."
            })

        session_id = user_message.get("id")

        if not session_id:
            session_id = str(uuid.uuid4())

        print("SESSION ID:", session_id)
        print("USER MESSAGE:", text)

        lex_response = lex.recognize_text(
            botId=BOT_ID,
            botAliasId=BOT_ALIAS_ID,
            localeId=LOCALE_ID,
            sessionId=session_id,
            text=text
        )

        print("LEX RESPONSE:", json.dumps(lex_response, default=str))

        lex_messages = lex_response.get("messages", [])

        response_text = "\n".join(
            message.get("content", "")
            for message in lex_messages
            if message.get("contentType") == "PlainText"
        )

        if not response_text:
            response_text = "Could you please repeat that?"

        return api_response(200, {
            "messages": [
                chatbot_message(response_text)
            ]
        })

    except Exception as error:
        print("LF0 ERROR:", str(error))

        return api_response(500, {
            "messages": [
                chatbot_message(
                    "Sorry, something went wrong. Please try again."
                )
            ]
        })