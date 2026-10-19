"""Provider metadata survives compaction, session reopen, and provider switches."""
import json

import httpx

from eirene.core.compact import compact
from eirene.core.session import Session
from eirene.providers import base
from eirene.providers.gemini import Gemini
from eirene.providers.openai_compat import OpenAICompatible


async def test_compact_resume_switch_and_return_preserves_signed_tools(workdir):
    session = Session.create(workdir)
    session.add_user('Inspect a.txt')
    part={'functionCall':{'name':'read_file','args':{'path':'a.txt'}},'thoughtSignature':'original-signature'}
    session.add_assistant('', [{'id':'call','name':'read_file','arguments':{'path':'a.txt'}}],gemini_parts=[part])
    session.add_tool_result('call','read_file','file contents')
    requests=[]
    def respond(request):
        payload=json.loads(request.content)
        requests.append(payload)
        if request.url.path.endswith('/chat/completions'):
            assert payload['messages'][-2]['tool_calls'][0]['id']=='call'
            body={'choices':[{'delta':{'content':'Continued'},'finish_reason':'stop'}]}
        else:
            if len(requests)>1:
                calls=[p for c in payload['contents'] for p in c['parts'] if 'functionCall' in p]
                assert calls==[part]
            body={'candidates':[{'content':{'parts':[{'text':'The file was inspected.'}]},'finishReason':'STOP'}]}
        return httpx.Response(200,text='data: '+json.dumps(body)+'\n\n')
    base.set_transport(httpx.MockTransport(respond))
    gemini=Gemini('key')
    openai=OpenAICompatible('key','https://mock.invalid/v1')
    resumed=None
    try:
        await compact(session,gemini,'gemini-3-flash')
        assert session.messages[-2]['gemini_parts']==[part]
        session.close()
        resumed=Session.resume(session.id)
        _=[e async for e in openai.stream(resumed.messages,'m')]
        _=[e async for e in gemini.stream(resumed.messages,'gemini-3-flash')]
        assert len(requests)==3
    finally:
        session.close()
        if resumed: resumed.close()
        await gemini.close()
        await openai.close()
        base.set_transport(None)
