import asyncio
from main import run_briefing


def lambda_handler(event, context):

    result = asyncio.run(run_briefing())

    return {
        "statusCode": 200,
        "body": result.summary()
    }