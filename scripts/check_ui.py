import copy
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from app import App

app = App(preview=True)
app.root.after_cancel(app.tick_job)
app.auto_hide_pending = False
app.root.geometry('440x650')
app.root.update()
assert app.engine is None
for title in ('Короткий трек', 'Очень длинное название трека с несколькими уточнениями версии и исполнителями ' * 5):
    state = copy.deepcopy(app.state)
    state['track']['title'] = title
    state['track']['artist'] = 'Очень длинный исполнитель, приглашённый артист и оркестр ' * 3
    for status in ('playing', 'paused'):
        state['track']['status'] = status
        app.view.render(state, app.config)
        app.root.update()
        for widget in (app.view.cover, app.view.track_title, app.view.play, app.view.open_link):
            bottom = widget.winfo_rooty() - app.root.winfo_rooty() + widget.winfo_height()
            assert bottom <= app.root.winfo_height(), (widget, bottom, app.root.winfo_height())
        assert app.view.track_title.cget('text').count('\n') <= 1
app.view.render({}, app.config)
app.root.update()
assert app.view.track_title.cget('text') == 'Включите музыку'
for page in ('settings', 'diagnostics', 'player'):
    app.view.navigate(page)
    app.view.render(app.state, app.config)
    app.root.update()
    assert app.view.pages[page].winfo_ismapped()
app.view.play.focus_set()
app.root.update()
assert app.view.play.cget('border_width') == 2
app.exit()
print('UI checks passed: isolated preview, long titles, play/pause, empty state, navigation and keyboard focus.')
