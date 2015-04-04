import sublime_plugin

try:  # Python 3
    from .haxe_helper import HaxeComplete_inst
    from .haxe_generate_code_helper import *
    from .haxe_format import format_statement
except (ValueError):  # Python 2
    from haxe_helper import HaxeComplete_inst
    from haxe_generate_code_helper import *
    from haxe_format import format_statement


class HaxeGenerateFieldEdit(sublime_plugin.TextCommand):

    def run(self, edit, text=None, pos=0):
        if text is None:
            return

        view = self.view
        set_pos(view, pos)

        new_lines = ''
        for c in text:
            if c == '\n':
                new_lines += c
            else:
                break

        _, after = count_blank_lines(view, pos)

        next_line_pos = view.full_line(pos).end()
        if after > 1:
            for i in range(0, after - 1):
                view.erase(edit, view.full_line(next_line_pos))

        if new_lines:
            self.view.run_command('insert', {"characters": new_lines})
            text = text[len(new_lines):]

        self.view.run_command('insert_snippet', {"contents": text})


class HaxeGenerateField(sublime_plugin.WindowCommand):

    def complete(self):
        view = self.window.active_view()

        if self.name in get_fieldnames(self.context):
            view.set_status(
                'haxe-status',
                'Field with name `%s` is already exist' % self.name)
            return

        pos, pre, post = self.find_insert_pos(view, self.field, self.name)

        if self.text is None:
            self.text = self.get_text()

        self.text = ''.join((pre, self.text, post))

        self.window.run_command(
            'haxe_generate_field_edit',
            {'text': self.text, 'pos': pos})

        self.context = None

    def find_insert_pos(self, view, field_type, field_name):
        pos_order = self.get_fields_order()
        ctx = self.context

        after_class = '\n' + ''.join(['\n' for i in range(0, 0)])
        between_vars = '\n' + ''.join(['\n' for i in range(0, 0)])
        between_functions = '\n' + ''.join(['\n' for i in range(0, 1)])
        post_between_groups = ''.join(['\n' for i in range(0, 1)])
        pre_between_groups = '\n' + post_between_groups

        has_fields = False
        scan = False

        for ft in reversed(pos_order):
            if not scan and ft != field_type:
                has_fields = has_fields or ctx['type'][ft]
                continue

            scan = True
            pre = between_vars
            if 'function' in ft:
                pre = between_functions
            post = '\n'

            last_tup = None
            for tup in reversed(ctx['type'][ft]):
                has_fields = True
                if field_name >= tup[1] or ft != field_type:
                    if ft != field_type:
                        pre = pre_between_groups
                        post = post_between_groups
                    elif not last_tup:
                        post = post_between_groups
                    return (tup[2].end(), pre, post)
                last_tup = tup

            if ft == field_type and last_tup is not None:
                post = between_vars
                if 'function' in ft:
                    post = between_functions
                pre = ''
                return (
                    find_line_start_pos(view, last_tup[2].begin()),
                    pre, post)

        pre = after_class
        if has_fields:
            post = post_between_groups
        else:
            post = ''

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

    def get_param_type(self):
        view = self.window.active_view()
        complete = HaxeComplete_inst()

        for r in view.sel():
            comps, hints = complete.get_haxe_completions(view, r.end())

        return hints

    def get_text(self):
        view = self.window.active_view()
        name = self.name
        mod, idx = self.get_mod(
            name, False, True,
            self.context['type']['group'] == 'abstract', self.static)

        types = None
        if 'meta.parameters.haxe.2' in self.context['scope'] and \
                self.caret_name:
            param_type = self.get_param_type()
            tp = param_type[0].split(':')[1]
            types = [r.strip() for r in tp.split('->')]

        if 'var' in self.field:
            text = '%svar %s:%s$0;'
            text = format_statement(view, text)
            ret = 'Dynamic'
            if types:
                ret = '$HX_W_AR->${HX_AR_W}'.join(types)
            text = text % (mod, name, '${%d:%s}' % (idx, ret))
        else:
            text = '%sfunction %s(%s):%s$HX_W_OCB{\n\t$0\n}'
            text = format_statement(view, text)
            params = ''
            ret = 'Void'
            ret_idx = idx + 1
            param_idx = 1

            if types:
                ret = types.pop()
                for tp in types:
                    if params:
                        params += '$HX_W_CM,${HX_CM_W}'
                    params += '${%d:p%d}$HX_W_C:${HX_C_W}%s' % (
                        ret_idx, param_idx, tp)
                    ret_idx += 1
                    param_idx += 1

            text = text % (
                mod,
                name,
                '${%d:%s}' % (idx, params),
                '${%d:%s}' % (ret_idx, ret))

        return text

    def on_input(self, name):
        name = name.strip()
        if not re_word.search(name):
            view = self.window.active_view()
            view.set_status('haxe-status', 'Invalid field name')
            return

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
        self.caret_name = name
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
