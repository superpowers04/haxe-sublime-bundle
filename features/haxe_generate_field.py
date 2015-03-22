import sublime_plugin

try:  # Python 3
    from .haxe_generate_code_helper import *
except (ValueError):  # Python 2
    from haxe_generate_code_helper import *


class HaxeGenerateField(sublime_plugin.WindowCommand):

    def complete(self):
        view = self.window.active_view()

        pos, pre, post = self.find_insert_pos(view, self.field, self.name)
        if post:
            pre = ''

        if self.text is None:
            self.text = self.get_text()

        self.text = ''.join((pre, self.text, post))

        self.window.run_command(
            'haxe_generate_code_edit',
            {'text': self.text, 'pos': pos})

    def find_insert_pos(self, view, field_type, field_name):
        pos_order = self.get_fields_order()
        ctx = self.context

        order = []
        for ft in pos_order:
            order.insert(0, ft)
            if ft == field_type:
                break

        pre = '\n'
        post = ''

        for ft in order:
            if 'function' in ft:
                pre = '\n\n'

            last_tup = None
            for tup in reversed(ctx['type'][ft]):
                if field_name >= tup[1] or ft != field_type:
                    return (tup[2].end(), pre, post)
                last_tup = tup

            if ft == field_type and last_tup is not None:
                post = '\n'
                if 'function' in ft:
                    post = '\n\n'
                return (
                    find_line_start_pos(view, last_tup[2].begin()),
                    pre, post)

            pre = '\n\n'

        pre = '\n\n'

        return (ctx['type']['block'].begin(), pre, post)

    def get_fields_order(self):
        view = self.window.active_view()
        def_order = 'VFvf'
        order = view.settings().get('haxe_fields_order', def_order)

        for c in def_order:
            if c not in order:
                order += c

        dct = {
            'V': FIELD_STATIC_VAR,
            'F': FIELD_STATIC_FUNC,
            'v': FIELD_VAR,
            'f': FIELD_FUNC
        }

        lst = []
        for c in order:
            if c not in dct:
                continue
            lst.append(dct[c])
            del dct[c]

        return lst

    def get_mod(self, name, o=False, p=True, i=False, s=True):
        mod = ''
        mod_map = {}

        order = self.get_mod_order()

        def add_mod(use, key, value):
            if use:
                mod_map[key] = value

        add_mod(o, 'o', 'override')
        add_mod(p, 'p', 'private' if name[0] == '_' else 'public')
        add_mod(i, 'i', 'inline')
        add_mod(s, 's', 'static')

        idx = 1
        for c in order:
            if c not in mod_map:
                continue
            mod += '${%d:%s }' % (idx, mod_map[c])
            del mod_map[c]
            idx += 1

        return mod, idx

    def get_mod_order(self):
        view = self.window.active_view()
        def_order = 'opis'
        order = view.settings().get('haxe_modifiers_order', def_order)

        for c in def_order:
            if c not in order:
                order += c

        return order

    def get_text(self):
        name = self.name
        mod, idx = self.get_mod(
            name, False, True,
            self.context['type']['group'] == 'abstract', self.static)

        if 'var' in self.field:
            text = '%svar %s:%s$0;' % (mod, name, '${%d:Int}' % idx)
        else:
            text = '%sfunction %s(%s):%s$TM_CSLB{\n\t$0\n}' % (
                mod,
                '${%d:%s}' % (idx, name),
                '$%d' % (idx + 1),
                '${%d:Void}' % (idx + 2))
        return text

    def on_input(self, name):
        self.name = name
        self.complete()

    @staticmethod
    def poll(ctx):
        if 'type' not in ctx or \
                ctx['type']['group'] not in ('abstract', 'class'):
            return []

        cmds = []

        def add(name, field):
            label = '...' if name is None else name
            cmds.append((
                'New %s %s' % (field, label),
                'haxe_generate_field',
                {'name': name, 'field': field}))

        if 'word' in ctx:
            add(ctx['word'], FIELD_VAR)
            add(ctx['word'], FIELD_STATIC_VAR)
            add(ctx['word'], FIELD_FUNC)
            add(ctx['word'], FIELD_STATIC_FUNC)

        add(None, FIELD_VAR)
        add(None, FIELD_STATIC_VAR)
        add(None, FIELD_FUNC)
        add(None, FIELD_STATIC_FUNC)

        return cmds

    def run(self, context=None, name=None, field=FIELD_VAR, text=None):
        win = self.window
        view = win.active_view()

        if view is None or view.is_loading() or not is_haxe_scope(view):
            return

        if context is None:
            context = get_context(view)
        self.context = context
        self.name = name
        self.field = field
        self.static = 'static' in field
        self.text = text

        if 'type' not in context:
            return

        if name is None:
            win.show_input_panel(
                'New %s' % field, '', self.on_input, None, None)
        else:
            self.complete()
