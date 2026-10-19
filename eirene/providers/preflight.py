"""Reject malformed conversation structure before making an API request."""
from __future__ import annotations

import re
from ..core.errors import ProviderError


def invalid(position, reason):
    raise ProviderError(f'Conversation message {position + 1}: {reason}. '
                        'Reopen the session or compact it; if the history was imported, check its tool-call records.')


def validate_history(messages):
    pending = {}
    for position, message in enumerate(messages):
        role = message.get('role')
        if role == 'tool':
            call_id = message.get('tool_call_id')
            if call_id not in pending:
                invalid(position, 'tool result has no matching pending call')
            name = message.get('name')
            if name and name != pending[call_id]:
                invalid(position, 'tool result name does not match its call')
            del pending[call_id]
            continue
        if pending:
            invalid(position, 'tool calls need their results before the next message')
        if role != 'assistant':
            continue
        calls = message.get('tool_calls') or []
        if not calls and message.get('response_items'):
            calls = [dict(id=item.get('call_id'), name=item.get('name'), arguments={})
                     for item in message['response_items'] if item.get('type') == 'function_call']
        for call in calls:
            call_id, name = call.get('id'), call.get('name')
            if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
                invalid(position, 'tool call requires an ID and name')
            if call_id in pending:
                invalid(position, 'duplicate tool call ID in the same batch')
            if not isinstance(call.get('arguments', {}), dict):
                invalid(position, 'tool arguments must be an object')
            pending[call_id] = name
    if pending:
        invalid(len(messages) - 1, 'tool calls have no results yet')


def validate_gemini(contents, model):
    major = re.search(r'gemini-(\d+)', model)
    required = major is not None and int(major[1]) >= 3
    # Gemini validates the current turn, beginning at the latest normal user
    # content (a functionResponse alone does not start a turn).
    start = 0
    for index, content in enumerate(contents):
        if content['role'] == 'user' and any('text' in part or 'inlineData' in part for part in content['parts']):
            start = index
    for index, content in enumerate(contents):
        calls = [part for part in content['parts'] if 'functionCall' in part]
        for part in calls:
            call = part['functionCall']
            if not call.get('name') or not isinstance(call.get('args', {}), dict):
                invalid(index, 'Gemini function call has invalid name or arguments')
        if required and index >= start and calls and not calls[0].get('thoughtSignature'):
            invalid(index, 'Gemini function call is missing its original thought signature')


def validate_anthropic(messages):
    for index, message in enumerate(messages):
        for block in message['content']:
            if block.get('type') == 'thinking' and not block.get('signature'):
                invalid(index, 'Claude thinking block is missing its original signature')
            if block.get('type') == 'tool_use' and not isinstance(block.get('input'), dict):
                invalid(index, 'Claude tool input must be an object')
