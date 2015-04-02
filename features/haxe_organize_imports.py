import sublime
import sublime_plugin
import re
from copy import deepcopy
from os.path import basename

try:  # Python 3
    from .haxe_helper import packageLine, show_quick_panel, \
        typeDecl, HaxeComplete_inst
    from .haxe_generate_code_helper import count_blank_lines
except (ValueError):  # Python 2
    from haxe_helper import packageLine, show_quick_panel, \
        typeDecl, HaxeComplete_inst
    from haxe_generate_code_helper import count_blank_lines


type_re = re.compile('[\w.]*[A-Z]\w*')
word_re = re.compile('\\b[_a-zA-Z]\w*\\b')
conditions_re = re.compile('[ \t]*#(if|elseif|else|end)', re.M)
import_line_re = re.compile(
    '^([ \t]*)import\s+'
    '('
    '((\\b[a-z]\w*\.)*)'
    '((\\b[A-Z]\w*\.?|\*)+)'
    '(\\b[_a-z]\w*|\*)?'
    ')\s*;', re.M)
using_line_re = re.compile(
    '^([ \t]*)using\s+'
    '('
    '((\\b[a-z]\w*\.)*)'
    '((\\b[A-Z]\w*\.?)+)'
    ')\s*;', re.M)


def add_type_path(type_map, typename, path):
    if typename in type_map:
        if is_string(type_map[typename]):
            if path != type_map[typename]:
                type_map[typename] = [type_map[typename], path]
        else:
            if path not in type_map[typename]:
                type_map[typename].append(path)
    else:
        type_map[typename] = path


def erase_line(view, edit, pos):
    rgn = view.full_line(pos)
    view.erase(edit, rgn)
    return rgn.end() - rgn.begin()


def get_cur_modulename(view):
    return basename(view.file_name()).partition('.')[0]


def get_cur_package(src):
    mo = packageLine.search(src)
    if mo is not None:
        return mo.group(1)
    return ''


def get_declared_typename_map(src):
    dct = {}

    for mo in typeDecl.finditer(src):
        dct[mo.group(2)] = True

    return dct


def get_full_imp(imppath, impname):
    if imppath == '':
        return impname
    if is_package(imppath) or not is_type(impname) or impname == '*':
        return '.'.join((imppath, impname))
    return imppath


def get_imported_clname_map(src, imp_to_ignore_map=None):
    dct = {}

    for mo in import_line_re.finditer(src):
        imp = mo.group(2)
        if imp_to_ignore_map is not None and imp in imp_to_ignore_map:
            continue
        impname = imp.rpartition('.')[2]
        dct[impname] = True

    return dct


def get_module_map(typenames):
    dct = {}

    for typename in typenames:
        if typename not in HaxeOrganizeImports.build_type_map:
            continue
        modules = HaxeOrganizeImports.build_type_map[typename]
        if not modules:
            continue
        if is_string(modules):
            if not is_package(modules):
                dct[modules] = True
        else:
            for module in modules:
                if not is_package(module):
                    dct[module] = True

    return dct


def get_used_typename_map(src):
    dct = {}

    for mo in type_re.finditer(src):
        if '.' not in mo.group(0):
            dct[mo.group(0)] = True

    return dct


def get_used_words_map(src):
    dct = {}

    for mo in word_re.finditer(src):
        dct[mo.group(0)] = True

    return dct


def get_view_src(view):
    return view.substr(sublime.Region(0, view.size()))


def init_build_class_map(view):
    if HaxeOrganizeImports.std_type_map is None:
        HaxeOrganizeImports.std_type_map = \
            init_type_map(HaxeComplete_inst().__class__.stdClasses)

    if HaxeOrganizeImports.build_classes is None:
        build = HaxeComplete_inst().get_build(view)
        HaxeOrganizeImports.build_classes, _ = build.get_types()

    HaxeOrganizeImports.build_type_map = init_type_map(
        HaxeOrganizeImports.build_classes,
        HaxeOrganizeImports.std_type_map)


def init_type_map(types, type_map=None):
    if type_map is None:
        type_map = {}
    else:
        type_map = deepcopy(type_map)

    for tp in types:
        tp, _, _ = tp.partition("<")
        path, _, typename = tp.rpartition(".")

        add_type_path(type_map, typename, path)

    return type_map


def is_haxe_scope(view):
    return view.score_selector(0, "source.haxe.2") > 0


def is_in_regions(regions, pos):
    for rgn in regions:
        if rgn.contains(pos):
            return True

    return False


def is_package(package):
    first_letter = package.rpartition('.')[2][0]
    return first_letter.lower() == first_letter


def is_string(value):
    val = False
    try:
        val = isinstance(value, str)
    except NameError:
        val = isinstance(value, basestring)

    return val


def is_type(name):
    first_letter = name[0]
    return first_letter.upper() == first_letter


def search_conditional_regions(src):
    lines = []
    regions = []

    for mo in conditions_re.finditer(src):
        lines.append((mo.start(0), mo.group(1) == 'end'))

    last_pos = -1
    for pos, is_end in lines:
        if last_pos != -1:
            regions.append(sublime.Region(last_pos, pos))
        if is_end:
            last_pos = -1
        else:
            last_pos = pos

    return regions


class HaxeOrganizeImportsEdit(sublime_plugin.TextCommand):

    def insert_imports(self, edit):
        view = self.view
        imps = HaxeOrganizeImports.active_inst.imps_to_add
        if not imps:
            return

        pos = HaxeOrganizeImports.active_inst.insert_pos
        indent = HaxeOrganizeImports.active_inst.indent
        ins = ''

        before, after = count_blank_lines(view, pos)

        next_line_pos = view.full_line(pos).end()
        for i in range(0, after - 1):
            view.erase(edit, view.full_line(next_line_pos))

        for i in range(0, 2 - before):
            ins += '\n'

        for imp in imps:
            ins += '%simport %s;\n' % (indent, imp)

        self.view.insert(edit, pos, ins)

        self.view.sel().clear()
        self.view.sel().add(sublime.Region(pos, pos))
        self.view.show_at_center(pos)

    def remove_imports(self, edit):
        lines = HaxeOrganizeImports.active_inst.lines_to_remove
        offset = 0

        for pt in lines:
            offset += erase_line(self.view, edit, pt - offset)

    def run(self, edit):
        if not HaxeOrganizeImports.active_inst:
            return

        self.remove_imports(edit)
        self.insert_imports(edit)

        HaxeOrganizeImports.active_inst.clean()


class HaxeOrganizeImportsEventListener(sublime_plugin.EventListener):

    def add_build_change_callback(self, view):
        if is_haxe_scope(view):
            view.settings().add_on_change(
                'haxe-build-id',
                lambda: self.on_build_change(view))

    def on_build_change(self, view):
        build = HaxeComplete_inst().get_build(view)
        if build is not None:
            HaxeOrganizeImports.build_classes, _ = build.get_types()
            HaxeOrganizeImports.build_type_map = None

    def on_load(self, view):
        self.add_build_change_callback(view)

    def on_pre_save(self, view):
        if not is_haxe_scope(view):
            return

        src = get_view_src(view)
        declared_typename_map = get_declared_typename_map(src)
        if not declared_typename_map:
            return

        cur_modulename = get_cur_modulename(view)
        cur_package = get_cur_package(src)

        if HaxeOrganizeImports.build_type_map is None:
            init_build_class_map(view)

        for typename in declared_typename_map:
            if typename == cur_modulename:
                continue
            add_type_path(
                HaxeOrganizeImports.build_type_map,
                typename,
                get_full_imp(cur_package, cur_modulename))


class HaxeOrganizeImports(sublime_plugin.WindowCommand):

    active_inst = None
    build_type_map = None
    build_classes = None
    std_type_map = None

    def add_unimported_classes(self):
        self.search_unimported_classes()

        if self.missing_impnames_to_prompt:
            self.prompt_classes_to_import()
        else:
            self.complete_adding_unimported_classes()

    def check_modules(self):
        module_map = get_module_map(self.used_typename_map.keys())
        imps_to_del = []

        for imp in self.imp_to_remove_map:
            if imp in module_map:
                imps_to_del.append(imp)

        for imp in imps_to_del:
            del self.imp_to_remove_map[imp]

    def clean(self):
        self.imps_to_add = None
        self.imp_to_remove_map = None
        self.lines_to_remove = None
        self.missing_imps = None
        self.used_words_map = None
        self.used_typename_map = None
        self.imp_to_ignore_map = None
        HaxeOrganizeImports.active_inst = None

    def complete_adding_unimported_classes(self):
        if self.missing_imps:
            self.imps_to_add.extend(self.missing_imps)

        sublime.set_timeout(lambda: self.complete_command(), 10)

    def complete_command(self):
        if self.imp_to_remove_map:
            for imp in self.imp_to_remove_map:
                if not self.remove or not self.imp_to_remove_map[imp]:
                    self.imps_to_add.append(imp)

        if self.sort:
            self.imps_to_add.sort()

        self.window.run_command('haxe_organize_imports_edit')

    def extract_imports(self):
        src = get_view_src(self.window.active_view())
        self.src_wo_imports = src
        conditional_regions = search_conditional_regions(src)
        self.imp_to_remove_map = {}
        self.imp_to_ignore_map = {}
        self.indent = ''
        self.insert_pos = -1
        self.imps_to_add = []
        splitted_imps_to_add = []
        wildcard_path_map = {}
        cur_package = get_cur_package(src)
        self.lines_to_remove = []
        offset = 0

        for mo in import_line_re.finditer(src):
            imp = mo.group(2)
            imppath, _, impname = imp.rpartition('.')

            self.src_wo_imports = \
                self.src_wo_imports[:mo.start(0) - offset] + \
                self.src_wo_imports[mo.end(0) - offset + 1:]
            offset += mo.end(0) - mo.start(0) + 1

            if is_in_regions(conditional_regions, mo.start(0)):
                self.imp_to_ignore_map[imp] = True
                continue

            if self.insert_pos == -1:
                self.insert_pos = mo.start(0)
                self.indent = mo.group(1)

            if imppath == '' or imppath == cur_package:
                self.imp_to_remove_map[imp] = True
            else:
                splitted_imps_to_add.append((imppath, impname))
            if impname == '*':
                wildcard_path_map[imppath] = True

            self.lines_to_remove.append(mo.start(0))

        while True:
            if not splitted_imps_to_add:
                break
            imppath, impname = splitted_imps_to_add.pop()
            if impname == '*' or imppath not in wildcard_path_map:
                self.imps_to_add.append(
                    get_full_imp(imppath, impname))

        offset = 0
        for mo in using_line_re.finditer(self.src_wo_imports):
            self.src_wo_imports = \
                self.src_wo_imports[:mo.start(0) - offset] + \
                self.src_wo_imports[mo.end(0) - offset + 1:]
            offset += mo.end(0) - mo.start(0) + 1

        self.used_words_map = get_used_words_map(self.src_wo_imports)
        self.used_typename_map = get_used_typename_map(self.src_wo_imports)

        if self.insert_pos == -1:
            self.insert_pos = self.get_insert_pos(src)

    def get_insert_pos(self, src):
        mo = packageLine.search(src)
        pos = 0
        if mo is not None:
            pos = mo.end(0)

        return pos

    @staticmethod
    def get_type_map(view):
        if HaxeOrganizeImports.build_type_map is None:
            init_build_class_map(view)

        return HaxeOrganizeImports.build_type_map

    def on_select_class_to_import(self, index):
        if index == -1:
            self.clean()
            return

        impname = self.missing_impnames_to_prompt.pop()
        self.imps_to_add.append(
            get_full_imp(
                HaxeOrganizeImports.build_type_map[impname][index],
                impname))

        if not self.missing_impnames_to_prompt:
            self.complete_adding_unimported_classes()
        else:
            self.prompt_classes_to_import()

    def on_select_import_to_remove(self, index):
        if index == -1:
            self.clean()
            return

        if index == 0:
            if self.add:
                sublime.set_timeout(lambda: self.add_unimported_classes(), 10)
            else:
                sublime.set_timeout(lambda: self.complete_command(), 10)
            return
        elif index < 3:
            for imp in self.imp_to_remove_map:
                self.imp_to_remove_map[imp] = \
                    True if index == 1 else False
        else:
            imp = sorted(self.imp_to_remove_map.keys())[index - 3]
            self.imp_to_remove_map[imp] = \
                not self.imp_to_remove_map[imp]

        self.prompt_imports_to_remove(index)

    def prompt_classes_to_import(self):
        impname = self.missing_impnames_to_prompt[-1]
        options = []

        for package in HaxeOrganizeImports.build_type_map[impname]:
            options.append('import %s' % get_full_imp(package, impname))

        show_quick_panel(
            self.window, options, self.on_select_class_to_import,
            sublime.MONOSPACE_FONT, 0)

    def prompt_imports_to_remove(self, selected_index=0):
        if not self.imp_to_remove_map:
            if self.add:
                self.add_unimported_classes()
            else:
                self.complete_command()
            return

        options = []
        options.append('Done')
        options.append('Check All')
        options.append('Uncheck All')

        sorted_imps = sorted(self.imp_to_remove_map.keys())
        for imp in sorted_imps:
            options.append(
                '[%s] remove %s' %
                ('x' if self.imp_to_remove_map[imp] else ' ', imp))

        show_quick_panel(
            self.window, options, self.on_select_import_to_remove,
            sublime.MONOSPACE_FONT, selected_index)

    def remove_unused_imports(self):
        used_imps = []

        for imp in self.imps_to_add:
            if imp in used_imps:
                continue

            impname = imp.rpartition('.')[2]
            if impname != '*':
                if impname not in self.used_words_map:
                    self.imp_to_remove_map[imp] = True
                    continue

            used_imps.append(imp)

        self.imps_to_add = used_imps

    def run(self, add=True, sort=True, remove=True, auto_remove=False):
        view = self.window.active_view()
        if HaxeOrganizeImports.active_inst or \
                view is None or \
                not is_haxe_scope(view):
            return

        HaxeOrganizeImports.active_inst = self
        self.add = add
        self.sort = sort
        self.remove = remove

        if HaxeOrganizeImports.build_type_map is None:
            init_build_class_map(self.window.active_view())

        self.extract_imports()
        self.remove_unused_imports()
        self.check_modules()

        if remove and not auto_remove:
            self.prompt_imports_to_remove()
        elif add:
            self.add_unimported_classes()
        else:
            self.complete_command()

    def search_unimported_classes(self):
        self.missing_imps = []
        self.missing_impnames_to_prompt = []
        if HaxeOrganizeImports.build_type_map is None:
            return

        src = get_view_src(self.window.active_view())
        unimported_typename_map = {}
        unimported_typenames_to_prompt_map = {}
        imported_clname_map = \
            get_imported_clname_map(src, self.imp_to_ignore_map)
        declared_typename_map = get_declared_typename_map(src)
        cur_package = get_cur_package(src)

        for typename in self.used_typename_map:
            if typename not in HaxeOrganizeImports.build_type_map or \
                    typename in imported_clname_map or \
                    typename in declared_typename_map:
                continue

            if is_string(HaxeOrganizeImports.build_type_map[typename]):
                package = HaxeOrganizeImports.build_type_map[typename]

                if cur_package == package or package == '':
                    continue

                unimported_typename_map[typename] = True
            else:
                unimported_typenames_to_prompt_map[typename] = True

        for typename in unimported_typename_map.keys():
            self.missing_imps.append(
                get_full_imp(
                    HaxeOrganizeImports.build_type_map[typename], typename))

        self.missing_impnames_to_prompt = \
            list(unimported_typenames_to_prompt_map.keys())
