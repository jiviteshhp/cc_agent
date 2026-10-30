"""Opt-in model evaluation with synthetic conversations only; no retries.

Run from the repo root: .venv/bin/python -m tests.evaluate_extraction
Uses configured Gemini access. Prints synthetic model output for human review;
never prints exception payloads or credentials. Not part of offline pytest.
"""
import asyncio
import json

from dotenv import load_dotenv

CASES = [
    ('details_and_correction', [
        {'role':'assistant', 'content':'किस आंख में तकलीफ़ है?'},
        {'role':'user', 'content':'दाईं में, माफ कीजिए बाईं आंख में। तीन दिन से लाल है और कल शाम से जलन है। सुबह पलक चिपकती है, पानी जैसा निकलता है, पीला नहीं।'},
        {'role':'assistant', 'content':'पहले कोई इलाज लिया?'},
        {'role':'user', 'content':'परसों डॉक्टर को दिखाया, बूंद का नाम याद नहीं, दिन में तीन बार डालता हूं, फायदा नहीं हुआ। पांच साल से शुगर है, बीपी नहीं। मेटफॉर्मिन पांच सौ मिलीग्राम सुबह शाम लेता हूं।'},
        {'role':'user', 'content':'धूल में जलन बढ़ती है, पढ़ने में परेशानी होती है। पहले भी पिछले साल ऐसा हुआ था। एक दवा से खुजली हुई थी, उसका नाम नहीं याद।'},
    ], 'Preserve corrected Left, separate timelines, watery/not yellow discharge, sticking lids, unnamed drops frequency/no benefit, diabetes duration, specific BP denial, metformin dose/frequency, dust trigger, reading impact, prior episode, unnamed drug reaction without inventing an allergy diagnosis.'),
    ('ambiguity_and_denial_scope', [
        {'role':'assistant', 'content':'दाईं आंख में दर्द है और आपको शुगर है, सही है?'},
        {'role':'user', 'content':'जी।'},
        {'role':'assistant', 'content':'कौन सी दवा लेते हैं?'},
        {'role':'user', 'content':'आंख की बूंद नहीं लेता, बीपी की एक गोली रोज लेता हूं, नाम नहीं मालूम। शायद दो दिन से है, नहीं, तारीख याद नहीं।'},
    ], 'Do not accept compound read-back from ji alone; do not infer hypertension just from a BP tablet; retain daily tablet/name uncertainty, no eye drops only, uncertain timing. No confident laterality or diabetes.'),
    ('no_patient_facts', [
        {'role':'assistant', 'content':'क्या आपको बाईं आंख में दर्द और शुगर है?'},
        {'role':'user', 'content':'आवाज नहीं आ रही, हेलो।'},
    ], 'Expected {}. Assistant suggestions and technical chatter are not patient facts.'),
]


async def main():
    load_dotenv()
    import llm
    for name, history, rubric in CASES:
        print(json.dumps({'case':name, 'review_against':rubric}), flush=True)
        try:
            result = await llm.extract(history)
        except Exception:
            # llm emits an allowlisted diagnostic, never the provider payload.
            print(json.dumps({'case':name, 'result':'evaluation_unavailable'}), flush=True)
            return
        print(json.dumps({'case':name, 'synthetic_output':result}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
