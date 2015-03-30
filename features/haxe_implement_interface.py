import codecs
import os.path
import re
import sublime
import sublime_plugin

try:  # Python 3
    from .haxe_generate_code_helper import *
    from .haxe_organize_imports import HaxeOrganizeImports
    from .haxe_helper import HaxeComplete_inst
except (ValueError):  # Python 2
    from haxe_generate_code_helper import *
    from haxe_organize_imports import HaxeOrganizeImports
    from haxe_helper import HaxeComplete_inst

re_comments = re.compile(
    r'(//[^\n\r]*?[\n\r]|/\*(.*?)\*/)', re.MULTILINE | re.DOTALL)
re_implements = re.compile(r'implements\s+([\w\.]+)', re.MULTILINE)
re_field = re.compile(r'(var|function)\s+(\w+)[^;]*;', re.MULTILINE)
re_import = re.compile(r'import\s+([\w\.*]+)[^;]*;', re.MULTILINE)
re_return = re.compile(r'\)\s*:\s*([\w\.<>-]+);', re.MULTILINE)


def is_full_path(path):
    return '.' in path


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


class HaxeImplementInterface(sublime_plugin.WindowCommand):

    def extract_fields(self, src):
        lst = []
        if src is None:
            return lst

        for mo in re_field.finditer(src):
            name = mo.group(2)
            if name in self.fieldnames:
                continue
            lst.append((mo.group(1), name, 'public ' + mo.group(0)))

        return lst

    def extract_type(self, src, start):
        br_begin = 0
        for i in range(start, len(src)):
            c = src[i]
            if c == '{':
                br_begin += 1
            elif c == '}':
                if br_begin == 0:
                    return src[start:i]
                br_begin -= 1

        return None

    def find_classpaths(self):
        view = self.window.active_view()
        self.classpaths = []

        build = HaxeComplete_inst().get_build(view)
        self.classpaths.extend(HaxeComplete_inst().__class__.stdPaths)

        for cp in build.classpaths:
            self.classpaths.append(os.path.join(build.cwd, cp))

        for lib in build.libs:
            if lib is not None:
                self.classpaths.append(lib.path)

    def find_fields(self):
        extends = []

        for iface in self.interfaces:
            s = codecs.open(iface[2], "r", "utf-8", "ignore")
            src = re_comments.sub('', s.read())
            imp_map = self.get_import_map(src)
            pat = 'interface\s+%s\s+(extends\s+([\w.]+))?\s*\{' % iface[0]
            mo = re.search(pat, src, re.MULTILINE)
            if mo:
                pos = mo.end(0)
                src_type = self.extract_type(src, pos)
                self.fields_to_insert.extend(self.extract_fields(src_type))

                if mo.group(2):
                    exname, ex = self.split_type(mo.group(2), imp_map)
                    if ex is not None and exname not in self.parsed_iname_map:
                        extends.append(
                            (exname, self.get_module_file_path(exname, ex)))

        if extends:
            self.interfaces = extends
            self.find_files()
            self.find_fields()

    def find_files(self):
        lst = []

        for iface in self.interfaces:
            iname = iface[0]
            ipath = iface[1]
            self.parsed_iname_map[iname] = True
            ifile = ''
            for cp in self.classpaths:
                if not cp:
                    continue
                fl = os.path.join(cp, ipath)
                if os.path.isfile(fl):
                    ifile = fl
                    break
            if ifile:
                lst.append((iname, ipath, ifile))

        self.interfaces = lst

    def find_interfaces(self):
        ctx = self.context
        view = self.window.active_view()
        src = view.substr(ctx['type']['region'])
        self.interfaces = []
        ifaces = []
        imp_map = self.get_import_map()

        for mo in re_implements.finditer(src):
            ifaces.append(mo.group(1))

        for iface in ifaces:
            type_name, type_path = self.split_type(iface, imp_map)

            if type_path is None:
                continue

            self.interfaces.append(
                (type_name, self.get_module_file_path(type_name, type_path)))

    def get_import_map(self, src=None):
        if src is None:
            view = self.window.active_view()
            src = re_comments.sub(
                '', view.substr(sublime.Region(0, view.size())))

        dct = {}

        for mo in re_import.finditer(src):
            imp_name = mo.group(1).rpartition('.')[2]
            dct[imp_name] = mo.group(1)

        return dct

    def get_module_file_path(self, type_name, type_path):
        if is_package(type_path):
            type_path += '.' + type_name
        stype_path = type_path.split('.')
        if len(stype_path) > 1 and \
                is_type(stype_path[-1]) and is_type(stype_path[-2]):
            stype_path.pop()
        path = os.path.join(*stype_path)
        return '%s.hx' % path

    def insert_fields(self):
        for field in self.fields_to_insert:
            ftype = field[0]
            fname = field[1]
            ftext = field[2]
            if ftype == FIELD_FUNC:
                ret = ''
                mo = re_return.search(ftext)
                if mo:
                    if mo.group(1) in ('Float', 'Int'):
                        ret = 'return 0;'
                    elif mo.group(1) == 'Void':
                        ret = ''
                    elif mo.group(1) == 'Bool':
                        ret = 'return false;'
                    else:
                        ret = 'return null;'
                ftext = ftext.replace(
                    ';', '$TM_CSLB{\n\t%s\n}' % ret)

            self.window.run_command(
                'haxe_generate_field',
                {'name': fname, 'field': ftype, 'text': ftext})

    @staticmethod
    def poll(ctx):
        if 'type' not in ctx or \
                ctx['type']['group'] != 'class':
            return []

        view = ctx['view']
        src = view.substr(ctx['type']['region'])
        if re_implements.search(src) is None:
            return []

        cmds = []

        cmds.append((
            'Implement Interface',
            'haxe_implement_interface',
            {}))

        return cmds

    def run(self, context=None):
        win = self.window
        view = win.active_view()

        if view is None or view.is_loading() or not is_haxe_scope(view):
            return

        if context is None:
            context = get_context(view)
        self.context = context
        self.fieldnames = get_fieldnames(self.context)

        if 'type' not in context:
            return

        self.type_map = \
            HaxeOrganizeImports.get_type_map(self.window.active_view())
        if self.type_map is None:
            return

        self.parsed_iname_map = {}
        self.fields_to_insert = []

        self.find_classpaths()
        self.find_interfaces()
        self.find_files()
        self.find_fields()
        self.insert_fields()

    def search_type_path(self, typ, imp_map):
        path = self.type_map[typ]
        imps = [imp_map[k] for k in imp_map]

        if is_string(path):
            for imp in imps:
                if path in imp:
                    return path
        else:
            for p in path:
                for imp in imps:
                    if p in imp:
                        return p

        return None

    def split_type(self, typ, imp_map):
        if is_full_path(typ):
            type_name = typ.rpartition('.')[2]
            type_path = typ
        elif typ in self.type_map:
            type_name = typ
            type_path = self.search_type_path(typ, imp_map)
        else:
            return None, None

        return type_name, type_path
