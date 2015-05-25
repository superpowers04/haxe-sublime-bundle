import os
import re
import sublime
import sublime_plugin

try:  # Python 3
    from .haxe_generate_code_helper import is_haxe_scope
except (ValueError):  # Python 2
    from haxe_generate_code_helper import is_haxe_scope

re_type = re.compile(r'(abstract|class|enum|interface|typedef)\s*\b([\w]*)\b')


class HaxeFixModule(sublime_plugin.TextCommand):

    @staticmethod
    def poll(ctx):
        cmds = []
        filename = os.path.splitext(os.path.basename(ctx.view.file_name()))[0]
        src = ctx.src
        mos = [mo for mo in re_type.finditer(src)]
        if len(mos) != 1:
            return []

        mo = mos[0]
        if filename != mo.group(2):
            cmds.append((
                'Rename %s %s to %s' % (mo.group(1), mo.group(2), filename),
                'haxe_fix_module',
                {}))

        return cmds

    def run(self, edit):
        view = self.view

        if view is None or view.is_loading() or not is_haxe_scope(view):
            return

        filename = os.path.splitext(os.path.basename(view.file_name()))[0]
        src = view.substr(sublime.Region(0, self.view.size()))

        mos = [mo for mo in re_type.finditer(src)]
        if len(mos) != 1:
            return

        mo = mos[0]
        view.replace(edit, sublime.Region(mo.start(2), mo.end(2)), filename)
        sublime.status_message(
            '%s %s renamed to %s' % (mo.group(1), mo.group(2), filename))
