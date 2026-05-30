import json
import os

import daily_longform_upload as base


def generate_topic(history):
    used_topics = [x.get("topic", "") for x in history if x.get("topic")]
    client = base.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_TEXT_MODEL", "gpt-4o-mini"),
        messages=[
            {
                "role": "system",
                "content": "You return only valid JSON. Do not include markdown fences or commentary.",
            },
            {
                "role": "user",
                "content": (
                    "Create one fresh Korean YouTube longform explainer topic as strict JSON. "
                    "Avoid every used topic. The tone should be informative, practical, and suitable for a Korean audience. "
                    "Fields required: id, topic, title, description, tags, subject, problem, solution. "
                    "description must include two short paragraphs and 5 Korean hashtags. "
                    "tags must be a list of 5 to 7 Korean strings. "
                    "subject must be an English visual prompt for realistic Korean documentary imagery. "
                    "problem and solution must be concise Korean phrases.\n\n"
                    f"Used topics:\n{json.dumps(used_topics, ensure_ascii=False)}"
                ),
            },
        ],
        temperature=0.85,
    )
    topic = json.loads(response.choices[0].message.content.strip())
    required = {"id", "topic", "title", "description", "tags", "subject", "problem", "solution"}
    missing = sorted(required - set(topic))
    if missing:
        raise RuntimeError(f"Generated topic is missing fields: {missing}")
    if topic["topic"] in used_topics:
        raise RuntimeError("Generated topic duplicated a used topic")
    return topic


def pick_topic(history):
    used = {x.get("topic") for x in history}
    for topic in base.TOPICS:
        if topic["topic"] not in used:
            return topic
    return generate_topic(history)


base.pick_topic = pick_topic


if __name__ == "__main__":
    base.main()
