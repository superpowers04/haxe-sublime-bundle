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

    def run(self, edit, text=None, pos=0, move=True):
        if text is None:
            return

        view = self.view

        old_pos = view.sel()[0].end()
        old_size = view.size()
        set_pos(view, pos, move)

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

        if not move:
            if old_pos >= pos:
                old_pos = old_pos + view.size() - old_size
            set_pos(view, old_pos, False)


class HaxeGenerateField(sublime_plugin.WindowCommand):

    def complete(self):
        view = self.window.active_view()

        if self.name in self.context.type.field_map:
            sublime.status_message(
                'Field with name `%s` is already exist' % self.name)
            return

        pos, pre, post = self.find_insert_pos(view, self.field, self.name)

        if self.text is None:
            self.text = self.get_text()

        self.text = ''.join((pre, self.text, post))

        self.window.run_command(
            'haxe_generate_field_edit',
            {'text': self.text, 'pos': pos, 'move': self.move_caret})

        self.context = None

    def find_insert_pos(self, view, field_type, field_name):
        ctx = self.context

        bl_top = get_blank_lines(view, 'haxe_bl_top')
        bl_var = get_blank_lines(view, 'haxe_bl_var')
        bl_method = get_blank_lines(view, 'haxe_bl_method', 1)
        bl_group = get_blank_lines(view, 'haxe_bl_group', 1)

        field_is_var = 'var' in field_type
        group_prop = view.settings().get(
            'haxe_group_property_and_accessors', True)
        has_fields = False
        scan = False

        group_order, group_svars, group_smethods = self.get_group_order()
        group_map = self.get_group_map(group_svars, group_smethods)

        for ft in reversed(group_order):
            group_is_var = 'var' in ft
            same_group = ft == field_type
            if not group_svars and field_is_var:
                same_group = field_is_var == group_is_var
            if not group_smethods and not field_is_var:
                same_group = field_is_var == group_is_var
            if not scan and not same_group:
                has_fields = has_fields or group_map[ft]
                continue

            scan = True
            pre = '\n' + bl_var
            post = bl_var
            if 'function' in ft:
                pre = '\n' + bl_method
                post = bl_method

            last_field = None
            for field in reversed(group_map[ft]):
                has_fields = True
                if group_prop and not field_is_var:
                    if self.is_getter_setter(field):
                        continue
                if field_name >= field.name or not same_group:
                    if not same_group:
                        pre = '\n' + bl_group
                        post = bl_group
                    elif not last_field:
                        post = bl_group
                    pos = field.region.end()
                    if group_prop and self.is_property(view, field) and \
                            (field_is_var or not same_group):
                        get_name = 'get_' + field.name
                        set_name = 'set_' + field.name
                        if get_name in ctx.type.field_map:
                            pre = '\n' + bl_group
                            pos = max(
                                pos, ctx.type.field_map[get_name].region.end())
                        if set_name in ctx.type.field_map:
                            pre = '\n' + bl_group
                            pos = max(
                                pos, ctx.type.field_map[set_name].region.end())
                    return (pos, pre, post)
                last_field = field

        pre = '\n' + bl_top
        if has_fields:
            post = bl_group
        else:
            post = ''

        return (ctx.type.block.begin(), pre, post)

    def get_group_order(self):
        view = self.window.active_view()
        def_order = 'VFvf'
        order = view.settings().get('haxe_fields_order', def_order)

        if 'v' not in order and 'V' not in order:
            order += 'v'
        if 'f' not in order and 'F' not in order:
            order += 'f'

        dct = {
            'V': FIELD_STATIC_VAR,
            'F': FIELD_STATIC_FUNC,
            'v': FIELD_VAR,
            'f': FIELD_FUNC
        }

        lst = []
        final_order = ''
        for c in order:
            if c not in dct:
                continue
            lst.append(dct[c])
            final_order += c
            del dct[c]

        group_svars = 'v' in final_order and 'V' in final_order
        group_smethods = 'f' in final_order and 'F' in final_order

        return lst, group_svars, group_smethods

    def get_group_map(self, group_svars, group_smethods):
        type = self.context.type
        group_map = {}

        def mix(fields1, fields2):
            lst = []

            i1, i2 = 0, 0
            n1, n2 = len(fields1), len(fields2)

            while(i1 < n1 or i2 < n2):
                f1 = None if i1 >= n1 else fields1[i1]
                f2 = None if i2 >= n2 else fields2[i2]

                if f1 and f2:
                    if f1.region.end() < f2.region.end():
                        lst.append(f1)
                        i1 += 1
                    else:
                        lst.append(f2)
                        i2 += 1
                elif f1:
                    lst.append(f1)
                    i1 += 1
                elif f2:
                    lst.append(f2)
                    i2 += 2

            return lst

        if not group_svars:
            group_map[FIELD_VAR] = group_map[FIELD_STATIC_VAR] = mix(
                type.vars, type.svars)
        else:
            group_map[FIELD_VAR] = type.vars
            group_map[FIELD_STATIC_VAR] = type.svars

        if not group_smethods:
            group_map[FIELD_FUNC] = group_map[FIELD_STATIC_FUNC] = mix(
                type.methods, type.smethods)
        else:
            group_map[FIELD_FUNC] = type.methods
            group_map[FIELD_STATIC_FUNC] = type.smethods

        return group_map

    def get_mods(self, name, o=False, p=True, i=False, s=True):
        mods = get_mods(
            self.window.active_view(),
            name[0] == '_', o, p, i, s)
        mod_lst = mods.split(' ')
        mods = ''

        idx = 1
        for mod in mod_lst:
            mods += '${%d:%s }' % (idx, mod)
            idx += 1

        return mods, idx

    def get_param_type(self):
        view = self.window.active_view()
        complete = HaxeComplete_inst()

        for r in view.sel():
            comps, hints = complete.get_haxe_completions(view, r.end())

        return hints

    def get_text(self):
        view = self.window.active_view()
        name = self.name
        mod, idx = self.get_mods(
            name, False, True,
            self.context.type.group == 'abstract', self.static)

        types = None
        if SCOPE_PARAMETERS in self.context.scope and \
                self.caret_name:
            param_type = self.get_param_type()
            if param_type:
                tp = param_type[0].split(':')[1]
                types = [r.strip() for r in tp.split('->')]

        if 'var' in self.field:
            text = '%svar %s:%s$0;'
            text = format_statement(view, text)
            ret = 'Dynamic'
            if types:
                ret = '$HX_W_AR->${HX_AR_W}'.join(types)
            text = text % (
                mod,
                '${%d:%s}' % (idx, name),
                '${%d:%s}' % (idx + 1, ret))
        else:
            text = '%sfunction %s(%s):%s$HX_W_OCB{\n\t$0\n}'
            text = format_statement(view, text)
            params = ''
            ret = 'Void'
            ret_idx = idx + 2
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
                '${%d:%s}' % (idx, name),
                '${%d:%s}' % (idx + 1, params),
                '${%d:%s}' % (ret_idx, ret))

        return text

    def is_getter_setter(self, func):
        fname = func[1]
        fname4 = fname[:4]
        if fname4 == 'get_' or fname4 == 'set_':
            prop_name = fname[4:]
            return prop_name in self.context.type.field_map

        return False

    def is_property(self, view, var):
        mo = re_prop_params.search(view.substr(var[2]))
        return mo is not None

    def on_input(self, name):
        name = name.strip()
        if not re_word.search(name):
            sublime.status_message('Invalid field name')
            return

        self.name = name
        self.complete()

    @staticmethod
    def poll(ctx):
        if not ctx.type or ctx.type.group not in ('abstract', 'class'):
            return []

        cmds = []

        def add(name, field):
            label = '...' if name is None else name
            cmds.append((
                'New %s %s' % (field, label),
                'haxe_generate_field',
                {'name': name, 'field': field}))

        if ctx.word and ctx.word.name not in ctx.type.field_map:
            add(ctx.word.name, FIELD_VAR)
            add(ctx.word.name, FIELD_STATIC_VAR)
            add(ctx.word.name, FIELD_FUNC)
            add(ctx.word.name, FIELD_STATIC_FUNC)

        add(None, FIELD_VAR)
        add(None, FIELD_STATIC_VAR)
        add(None, FIELD_FUNC)
        add(None, FIELD_STATIC_FUNC)

        return cmds

    def run(self, name=None, field=FIELD_VAR, text=None, move=False):
        win = self.window
        view = win.active_view()

        if view is None or view.is_loading() or not is_haxe_scope(view):
            return

        self.context = get_context(view)
        self.name = name
        self.caret_name = name
        self.field = field
        self.static = 'static' in field
        self.text = text
        self.move_caret = text is None or move

        if not self.context.type:
            return

        if name is None:
            win.show_input_panel(
                'New %s' % field, '', self.on_input, None, None)
        else:
            self.complete()
