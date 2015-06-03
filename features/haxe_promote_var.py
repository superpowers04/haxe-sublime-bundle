import re
import sublime_plugin

try:  # Python 3
    from .haxe_generate_code_helper import *
except (ValueError):  # Python 2
    from haxe_generate_code_helper import *


class HaxePromoteVarEdit(sublime_plugin.TextCommand):

    def run(self, edit, pos0, pos1):
        self.view.erase(edit, sublime.Region(pos0, pos1))


class HaxePromoteVar(sublime_plugin.WindowCommand):

    def on_select(self, index):
        if index == -1:
            return

        self.window.run_command('haxe_promote_var_edit', {
            'pos0': self.pos0,
            'pos1': self.pos1
        })
        self.window.run_command('haxe_generate_field', {
            'name': self.name,
            'field': FIELD_VAR if index == 0 else FIELD_STATIC_VAR
        })

    @staticmethod
    def poll(ctx):
        view = ctx.view
        cmds = []

        if not ctx.method or not ctx.word:
            return cmds

        src = view.substr(ctx.method.region)
        if re.search(r'var\s+' + ctx.word.name, src):
            cmds.append((
                'Promote Local Variable ...',
                'haxe_promote_var',
                {}))

        return cmds

    def run(self):
        win = self.window
        view = win.active_view()

        if view is None or view.is_loading() or not is_haxe_scope(view):
            return

        self.context = get_context(view)

        if not self.context.method or not self.context.word:
            return

        re_var = re.compile(r'(var\s+)' + self.context.word.name)
        src = view.substr(self.context.method.region)
        last_mo = None
        method_pos = self.context.method.region.begin()
        word_pos = self.context.word.region.begin()

        for mo in re_var.finditer(src):
            if mo.start(0) + method_pos > word_pos:
                break
            last_mo = mo

        if last_mo:
            self.pos0 = last_mo.start(1) + method_pos
            self.pos1 = last_mo.end(1) + method_pos
            self.name = self.context.word.name
            options = [
                'New var %s' % self.name,
                'New static var %s' % self.name]
            win.show_quick_panel(
                options, self.on_select, sublime.MONOSPACE_FONT, 0)
