import sublime
import sublime_plugin
import re
from copy import deepcopy
from os.path import basename

try:  # Python 3
    from ..HaxeHelper import importLine, packageLine, show_quick_panel, \
        typeDecl, HaxeComplete_inst
except (ValueError):  # Python 2
    from HaxeHelper import importLine, packageLine, show_quick_panel, \
        typeDecl, HaxeComplete_inst


class_re = re.compile('[\w.]*[A-Z]\w*')
conditions_re = re.compile('[ \t]*#(if|elseif|else|end)', re.M)


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


def get_full_module(package_or_module, classname):
    if package_or_module == '':
        return classname
    if is_package(package_or_module):
        return '.'.join((package_or_module, classname))
    return package_or_module


def get_imported_clname_map(src, ignored_class_map=None):
    dct = {}

    for mo in importLine.finditer(src):
        cl = mo.group(2)
        if ignored_class_map is not None and cl in ignored_class_map:
            continue
        clname = cl.rpartition('.')[2]
        dct[clname] = True

    return dct


def get_module_map(typenames):
    dct = {}

    for typename in typenames:
        if typename not in HaxeOrganizeImports.build_class_map:
            continue
        modules = HaxeOrganizeImports.build_class_map[typename]
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

    for mo in class_re.finditer(src):
        if '.' not in mo.group(0):
            dct[mo.group(0)] = True

    return dct


def get_view_src(view):
    return view.substr(sublime.Region(0, view.size()))


def init_build_class_map(view):
    if HaxeOrganizeImports.std_class_map is None:
        HaxeOrganizeImports.std_class_map = \
            init_class_map(HaxeComplete_inst().__class__.stdClasses)

    if HaxeOrganizeImports.build_classes is None:
        build = HaxeComplete_inst().get_build(view)
        HaxeOrganizeImports.build_classes, _ = build.get_types()

    HaxeOrganizeImports.build_class_map = init_class_map(
        HaxeOrganizeImports.build_classes,
        HaxeOrganizeImports.std_class_map)


def init_class_map(classes, class_map=None):
    if class_map is None:
        class_map = {}
    else:
        class_map = deepcopy(class_map)

    for cl in classes:
        cl, _, _ = cl.partition("<")
        package, _, clname = cl.rpartition(".")

        add_type_path(class_map, clname, package)

    return class_map


def is_haxe_scope(view):
    return view.score_selector(0, "source.haxe.2") > 0


def is_in_regions(regions, pos):
    for rgn in regions:
        if rgn.contains(pos):
            return True

    return False


def is_package(package):
    first_letter = package.rpartition('.')[2][:1]
    return first_letter.lower() == first_letter


def is_string(value):
    return type(value) == type(' ')


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
        classes = HaxeOrganizeImports.active_inst.classes_to_import
        pos = HaxeOrganizeImports.active_inst.insert_pos
        indent = HaxeOrganizeImports.active_inst.indent
        ins = HaxeOrganizeImports.active_inst.empty_lines_before

        for cl in classes:
            ins += '%simport %s;\n' % (indent, cl)

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
        HaxeOrganizeImports.build_classes, _ = build.get_types()
        HaxeOrganizeImports.build_class_map = None

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

        if HaxeOrganizeImports.build_class_map is None:
            init_build_class_map(view)

        for typename in declared_typename_map:
            if typename == cur_modulename:
                continue
            add_type_path(
                HaxeOrganizeImports.build_class_map,
                typename,
                get_full_module(cur_package, cur_modulename))


class HaxeOrganizeImports(sublime_plugin.WindowCommand):

    active_inst = None
    build_class_map = None
    build_classes = None
    std_class_map = None

    def add_unimported_classes(self):
        self.search_unimported_classes()

        if self.unimported_clnames_to_prompt:
            self.prompt_classes_to_import()
        else:
            self.complete_adding_unimported_classes()

    def check_modules(self):
        module_map = get_module_map(self.used_typename_map.keys())
        classes_to_del = []

        for cl in self.classes_to_remove_map:
            if cl in module_map:
                classes_to_del.append(cl)

        for cl in classes_to_del:
            del self.classes_to_remove_map[cl]

    def clean(self):
        self.classes_to_import = None
        self.classes_to_remove_map = None
        self.lines_to_remove = None
        self.unimported_classes = None
        self.used_typename_map = None
        self.ignored_class_map = None
        HaxeOrganizeImports.active_inst = None

    def complete_adding_unimported_classes(self):
        if self.unimported_classes:
            self.classes_to_import.extend(self.unimported_classes)

        sublime.set_timeout(lambda: self.complete_command(), 10)

    def complete_command(self):
        if self.classes_to_remove_map:
            for cl in self.classes_to_remove_map:
                if not self.remove or not self.classes_to_remove_map[cl]:
                    self.classes_to_import.append(cl)

        if self.sort:
            self.classes_to_import.sort()

        self.window.run_command('haxe_organize_imports_edit')

    def extract_imports(self):
        src = get_view_src(self.window.active_view())
        conditional_regions = search_conditional_regions(src)
        self.classes_to_remove_map = {}
        self.ignored_class_map = {}
        self.indent = ''
        self.empty_lines_before = ''
        self.insert_pos = -1
        self.classes_to_import = []
        classes_to_import_parts = []
        wildcard_package_map = {}
        cur_package = get_cur_package(src)
        self.used_typename_map = get_used_typename_map(src)
        self.lines_to_remove = []

        for mo in importLine.finditer(src):
            cl = mo.group(2)

            if is_in_regions(conditional_regions, mo.start(0)):
                self.ignored_class_map[cl] = True
                continue

            if self.insert_pos == -1:
                self.insert_pos = mo.start(0)
                self.indent = mo.group(1)

            package, _, clname = cl.rpartition('.')

            if package == '' or package == cur_package:
                self.classes_to_remove_map[cl] = True
            else:
                classes_to_import_parts.append((package, clname))
            if clname == '*':
                wildcard_package_map[package] = True

            self.lines_to_remove.append(mo.start(0))

        while True:
            if not classes_to_import_parts:
                break
            package, clname = classes_to_import_parts.pop()
            if clname == '*' or package not in wildcard_package_map:
                self.classes_to_import.append(get_full_module(package, clname))

        if self.insert_pos == -1:
            self.insert_pos = self.get_insert_pos(src)

    def get_insert_pos(self, src):
        mo = packageLine.search(src)
        pos = 0
        if mo is not None:
            pos = mo.end(0)
            self.empty_lines_before = '\n\n'

        return pos

    def on_select_class_to_import(self, index):
        if index == -1:
            index = 0
        clname = self.unimported_clnames_to_prompt[-1]
        self.classes_to_import.append(
            get_full_module(
                HaxeOrganizeImports.build_class_map[clname][index],
                clname))

        self.unimported_clnames_to_prompt.pop()

        if not self.unimported_clnames_to_prompt:
            self.complete_adding_unimported_classes()
        else:
            self.prompt_classes_to_import()

    def on_select_import_to_remove(self, index):
        if index == -1:
            index = 0
        if index == 0:
            if self.add:
                sublime.set_timeout(lambda: self.add_unimported_classes(), 10)
            else:
                sublime.set_timeout(lambda: self.complete_command(), 10)
            return
        elif index < 3:
            for cl in self.classes_to_remove_map:
                self.classes_to_remove_map[cl] = \
                    True if index == 1 else False
        else:
            cl = sorted(self.classes_to_remove_map.keys())[index - 3]
            self.classes_to_remove_map[cl] = \
                not self.classes_to_remove_map[cl]

        self.prompt_imports_to_remove()

    def prompt_classes_to_import(self):
        clname = self.unimported_clnames_to_prompt[-1]
        options = []

        for package in HaxeOrganizeImports.build_class_map[clname]:
            options.append('import %s' % get_full_module(package, clname))

        show_quick_panel(
            self.window, options, self.on_select_class_to_import,
            sublime.MONOSPACE_FONT, 0)

    def prompt_imports_to_remove(self):
        if not self.classes_to_remove_map:
            if self.add:
                self.add_unimported_classes()
            else:
                self.complete_command()
            return

        options = []
        options.append('Done')
        options.append('Check All')
        options.append('Uncheck All')

        sorted_classes = sorted(self.classes_to_remove_map.keys())
        for cl in sorted_classes:
            options.append(
                '[%s] remove %s' %
                ('x' if self.classes_to_remove_map[cl] else ' ', cl))

        show_quick_panel(
            self.window, options, self.on_select_import_to_remove,
            sublime.MONOSPACE_FONT, 0)

    def remove_unused_imports(self):
        used_classes = []

        for cl in self.classes_to_import:
            if cl in used_classes:
                continue

            clname = cl.rpartition('.')[2]
            if clname != '*':
                if clname not in self.used_typename_map:
                    self.classes_to_remove_map[cl] = True
                    continue

            used_classes.append(cl)

        self.classes_to_import = used_classes

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

        if HaxeOrganizeImports.build_class_map is None:
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
        src = get_view_src(self.window.active_view())
        unimported_clname_map = {}
        unimported_clnames_to_prompt_map = {}
        imported_clname_map = \
            get_imported_clname_map(src, self.ignored_class_map)
        declared_typename_map = get_declared_typename_map(src)
        cur_package = get_cur_package(src)

        for clname in self.used_typename_map:
            if clname not in HaxeOrganizeImports.build_class_map or \
                    clname in imported_clname_map or \
                    clname in declared_typename_map:
                continue

            if is_string(HaxeOrganizeImports.build_class_map[clname]):
                package = HaxeOrganizeImports.build_class_map[clname]

                if cur_package == package or package == '':
                    continue

                unimported_clname_map[clname] = True
            else:
                unimported_clnames_to_prompt_map[clname] = True

        self.unimported_classes = []
        for clname in unimported_clname_map.keys():
            self.unimported_classes.append(
                get_full_module(
                    HaxeOrganizeImports.build_class_map[clname], clname))

        self.unimported_clnames_to_prompt = \
            list(unimported_clnames_to_prompt_map.keys())
