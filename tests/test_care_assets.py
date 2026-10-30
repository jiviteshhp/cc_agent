"""Product assets and generated source clips remain local and accurately labelled."""
import asyncio
import httpx
import main


def test_care_home_source_audio_and_private_routes():
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://localhost:8001') as c:
            page=await c.get('/care')
            assert page.status_code==200 and 'Care workspace' in page.text
            home=await c.get('/')
            assert home.status_code==200 and "Doctor's portal" in home.text
            media=(await c.get('/care/api/intake-audio')).json()
            assert media['intake-p1']['text']=='दाईं आँख से धुंधला दिखता है।'
            assert media['intake-p1']['start']==0 and media['intake-p1']['end']>0
            clip=await c.get(media['intake-p1']['url'])
            assert clip.content[:4]==b'RIFF'
            assert (await c.get('/care/audio/unknown.wav')).status_code==404
            assert (await c.get('/care/assets/main.py')).status_code==404
            assert (await c.post('/care/api/action',json={'action':'reset'})).status_code==403
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.phone_app),base_url='http://localhost:8002') as c:
            for path in ('/care','/care/api/state','/care/api/reports','/care/api/intake.pdf','/care/api/intake-audio',
                         '/doctor','/doctor/api/live','/doctor/api/workspace','/doctor/assets/doctor.js',
                         '/doctor/api/reports/prepared/pdf'):
                assert (await c.get(path)).status_code==404
    asyncio.run(run())
