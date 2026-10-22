"""Interactive popup navigation and catalog installation workflows."""
import asyncio
import time

import pytest

from textual.widgets import Tree

from eirene.app import Eirene
from eirene.commands import dispatch
from eirene.core.session import Session
from eirene.ui.choice_popup import ChoicePopup
from eirene.ui.session_tree import SessionTreeScreen


def child_of(parent, label):
    child = Session.create(parent.sandbox)
    child.start()
    child.add_note('delegation', parent_id=parent.id, agent=label, status='running')
    child.add_user('Inspect files')
    child.add_assistant('Inspected the project')
    child.add_note('delegation_status',status='completed')
    child.close()
    return child


async def wait_for_popup(app, pilot, screen_type):
    # pilot.pause() waits for UI messages, not work running in a background thread.
    async with asyncio.timeout(5):
        while not isinstance(app.screen, screen_type) or not app.screen.is_mounted:
            await asyncio.sleep(0.01)
    await pilot.pause()


@pytest.mark.parametrize('load_delay', [0, 0.1])
async def test_tree_popup_opens_child_and_mother(workdir, monkeypatch, load_delay):
    from eirene.commands import subagents
    original = subagents.session_tree

    def load_tree(*args):
        time.sleep(load_delay)
        return original(*args)

    monkeypatch.setattr(subagents, 'session_tree', load_tree)
    app = Eirene(workdir)
    async with app.run_test(size=(110,36)) as pilot:
        await pilot.pause()
        mother = app.session
        mother.add_user('Mother task')
        first = child_of(mother,'Explorer')
        second = child_of(mother,'Reviewer')
        task = asyncio.create_task(dispatch(app,'/subagents'))
        await wait_for_popup(app, pilot, SessionTreeScreen)
        assert isinstance(app.screen,SessionTreeScreen)
        tree = app.screen.query_one(Tree)
        assert len(tree.root.children) == 2
        assert 'mother session' in str(tree.root.label)
        child = app.screen.nodes[first.id]
        tree.move_cursor(child)
        await pilot.press('enter')
        await task
        assert app.session.id == first.id
        assert any(m.get('content') == 'Inspected the project' for m in app.session.messages)
        task = asyncio.create_task(dispatch(app,'/subagents'))
        await wait_for_popup(app, pilot, SessionTreeScreen)
        assert app.screen.current == first.id
        assert second.id in app.screen.nodes
        await pilot.press('m')
        await task
        assert app.session.id == mother.id


async def test_tree_escape_preserves_session_and_active_work(workdir):
    app = Eirene(workdir)
    async with app.run_test(size=(100,32)) as pilot:
        await pilot.pause()
        mother = app.session
        mother.add_user('Mother task')
        child_of(mother,'Reviewer')
        app.turn = asyncio.create_task(asyncio.Event().wait())
        task = asyncio.create_task(dispatch(app,'/subagents'))
        await wait_for_popup(app, pilot, SessionTreeScreen)
        assert isinstance(app.screen, SessionTreeScreen)
        assert not app.screen.allow_switch
        await pilot.press('enter','escape')
        await task
        assert not app.turn.done()
        assert app.session.id == mother.id
        app.turn.cancel()
        await asyncio.gather(app.turn,return_exceptions=True)


async def test_plugin_catalog_popup_install_and_toggle(workdir, tmp_path, monkeypatch):
    # Use the real local importer while avoiding a network dependency.
    from eirene.core.plugin_install import install as local_install
    from eirene.commands import plugins as command
    bundle = tmp_path/'ponytail'
    (bundle/'skills'/'focused').mkdir(parents=True)
    (bundle/'plugin.json').write_text('{"name":"ponytail","description":"Focused work"}')
    (bundle/'skills'/'focused'/'SKILL.md').write_text('---\nname: focused\ndescription: Focused work\n---\nStay focused.')
    sources=[]
    def install(source):
        sources.append(source)
        return local_install(str(bundle))
    monkeypatch.setattr(command,'install',install)
    app = Eirene(workdir)
    async with app.run_test(size=(110,36)) as pilot:
        await pilot.pause()
        task=asyncio.create_task(dispatch(app,'/plugins'))
        await pilot.pause()
        assert isinstance(app.screen,ChoicePopup)
        assert any(row[0]=='install:ponytail' for row in app.screen.options)
        picker=app.screen.query_one('Picker')
        picker.index=next(i for i,row in enumerate(picker.options) if row[0]=='install:ponytail')
        await pilot.press('enter')
        await wait_for_popup(app, pilot, ChoicePopup)
        assert sources == ['ponytail']
        assert isinstance(app.screen,ChoicePopup)
        row=next(row for row in app.screen.options if row[0]=='installed:ponytail')
        assert row[2]=='enabled'
        assert not app.config.get('plugin_trust',{}).get('ponytail')
        picker=app.screen.query_one('Picker')
        picker.index=next(i for i,row in enumerate(picker.options) if row[0]=='installed:ponytail')
        await pilot.press('enter')
        await pilot.pause()
        assert isinstance(app.screen,ChoicePopup)
        await pilot.press('enter')  # Disable the installed plugin.
        await pilot.pause()
        assert not app.config.plugin_enabled('ponytail')
        await pilot.press('escape')
        await task
