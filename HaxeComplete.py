# -*- coding: utf-8 -*-

import sys
#sys.path.append("/usr/lib/python2.6/")
#sys.path.append("/usr/lib/python2.6/lib-dynload")

import sublime, sublime_plugin
import subprocess, time
import tempfile
import os, signal
import stat

#import xml.parsers.expat
import re
import codecs
import glob
import hashlib
import shutil
import functools

# Information about where the plugin is running from
plugin_file = __file__
plugin_filepath = os.path.realpath(plugin_file)
plugin_path = os.path.dirname(plugin_filepath)

# Reload modules
reloader = 'features.haxe_reload_modules'
if sys.version_info >= (3,):
    reloader = 'Haxe.' + reloader
if reloader in sys.modules:
    sys.modules[reloader].reload_modules()

try: # Python 3

    # Import the features module, including the haxelib and key commands etc
    from .features import *
    from .features.haxelib import *

    # Import the helper functions and regex helpers
    from .features.haxe_helper import runcmd, show_quick_panel, cache, parse_sig, get_env
    from .features.haxe_helper import spaceChars, wordChars, importLine, packageLine
    from .features.haxe_helper import compactFunc, compactProp, libLine, classpathLine, typeDecl
    from .features.haxe_helper import libFlag, skippable, inAnonymous, extractTag
    from .features.haxe_helper import variables, functions, functionParams, paramDefault
    from .features.haxe_helper import isType, comments, haxeVersion, haxeFileRegex, controlStruct
    from .features.haxe_errors import highlight_errors, extract_errors

except (ValueError): # Python 2

    # Import the features module, including the haxelib and key commands etc
    from features import *
    from features.haxelib import *

    # Import the helper functions and regex helpers
    from features.haxe_helper import runcmd, show_quick_panel, cache, parse_sig, get_env
    from features.haxe_helper import spaceChars, wordChars, importLine, packageLine
    from features.haxe_helper import compactFunc, compactProp, libLine, classpathLine, typeDecl
    from features.haxe_helper import libFlag, skippable, inAnonymous, extractTag
    from features.haxe_helper import variables, functions, functionParams, paramDefault
    from features.haxe_helper import isType, comments, haxeVersion, haxeFileRegex, controlStruct
    from features.haxe_errors import highlight_errors, extract_errors

# For running background tasks

from subprocess import Popen, PIPE
try:
  STARTUP_INFO = subprocess.STARTUPINFO()
  STARTUP_INFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW
  STARTUP_INFO.wShowWindow = subprocess.SW_HIDE
except (AttributeError):
    STARTUP_INFO = None

# For parsing xml

from xml.etree import ElementTree
from xml.etree.ElementTree import TreeBuilder as XMLTreeBuilder

try :
    from elementtree import SimpleXMLTreeBuilder # part of your codebase
    ElementTree.XMLTreeBuilder = SimpleXMLTreeBuilder.TreeBuilder
except ImportError as e:
    pass # ST3

try :
    stexec = __import__("exec")
    ExecCommand = stexec.ExecCommand
    AsyncProcess = stexec.AsyncProcess
except ImportError as e :
    import Default
    stexec = getattr( Default , "exec" )
    ExecCommand = stexec.ExecCommand
    AsyncProcess = stexec.AsyncProcess
    unicode = str #dirty...


class HaxeLib :

    available = {}
    basePath = None

    def __init__( self , name , dev , version ):
        self.name = name
        self.dev = dev
        self.version = version
        self.classes = None
        self.packages = None

        if self.dev :
            self.path = self.version
            self.version = "dev"
        else :
            self.path = os.path.join( HaxeLib.basePath , self.name , ",".join(self.version.split(".")) )

        #print(self.name + " => " + self.path)

    def extract_types( self ):

        if self.dev is True or ( self.classes is None and self.packages is None ):
            self.classes, self.packages = HaxeComplete.inst.extract_types(
                self.path ,
                cache_name = '%s_%s.cache' % (self.name, self.version) )

        return self.classes, self.packages

    @staticmethod
    def get( name ) :
        if( name in HaxeLib.available.keys()):
            return HaxeLib.available[name]
        else :
            sublime.status_message( "Haxelib : "+ name +" project not installed" )
            return None

    @staticmethod
    def get_completions() :
        comps = []
        for l in HaxeLib.available :
            lib = HaxeLib.available[l]
            comps.append( ( lib.name + " [" + lib.version + "]" , lib.name ) )

        return comps

    @staticmethod
    def scan( view ) :

        settings = view.settings()
        haxelib_path = settings.get("haxelib_path" , "haxelib")

        hlout, hlerr = runcmd( [haxelib_path , "config" ] )
        HaxeLib.basePath = hlout.strip()

        HaxeLib.available = {}

        hlout, hlerr = runcmd( [haxelib_path , "list" ] )

        for l in hlout.split("\n") :
            found = libLine.match( l )
            if found is not None :
                name, dev, version = found.groups()
                lib = HaxeLib( name , dev is not None , version )

                HaxeLib.available[ name ] = lib


inst = None

documentationStore = {}

class BuildCache:
    def __init__(self, path, raw, build, target):
        self.path = path
        self.raw = raw
        self.build = build
        self.target = target


class HaxeBuild :

    #auto = None
    targets = ["js","cpp","swf","neko","php","java","cs","x","python"]
    nme_targets = [
        ("Flash - test","flash -debug","test"),
        ("Flash - build only","flash -debug","build"),
        ("Flash - release","flash","build"),
        ("HTML5 - test","html5 -debug","test"),
        ("HTML5 - build only","html5 -debug","build"),
        ("HTML5 - release","html5","build"),
        ("C++ - test","cpp -debug","test"),
        ("C++ - build only","cpp -debug","build"),
        ("C++ - release","cpp","build"),
        ("Linux - test","linux -debug","test"),
        ("Linux - build only","linux -debug","build"),
        ("Linux - release","linux","build"),
        ("Linux 64 - test","linux -64 -debug","test"),
        ("Linux 64 - build only","linux -64 -debug","build"),
        ("Linux 64 - release","linux -64","build"),
        ("iOS - test in iPhone simulator","ios -simulator -debug","test"),
        ("iOS - test in iPad simulator","ios -simulator -ipad -debug","test"),
        ("iOS - update XCode project","ios -debug","update"),
        ("iOS - release","ios","build"),
        ("Android - test","android -debug","test"),
        ("Android - build only","android -debug","build"),
        ("Android - release","android","build"),
        ("WebOS - test", "webos -debug","test"),
        ("WebOS - build only", "webos -debug","build"),
        ("WebOS - release", "webos","build"),
        ("Neko - test","neko -debug","test"),
        ("Neko - build only","neko -debug","build"),
        ("Neko - release","neko","build"),
        ("Neko 64 - test","neko -64 -debug","test"),
        ("Neko 64 - build only","neko -64 -debug","build"),
        ("Neko 64 - release","neko -64","build"),
        ("BlackBerry - test","blackberry -debug","test"),
        ("BlackBerry - build only","blackberry -debug","build"),
        ("BlackBerry - release","blackberry","build"),
        ("Emscripten - test", "emscripten -debug","test"),
        ("Emscripten - build only", "emscripten -debug","build"),
        ("Emscripten - release", "emscripten","build"),
    ]
    nme_target = ("Flash - test","flash -debug","test")

    flambe_targets = [
        ("Flash - test", "run flash --debug" ),
        ("Flash - build only", "build flash --debug" ),
        ("HTML5 - test", "run html --debug" ),
        ("HTML5 - build only" , "build html --debug"),
        ("Android - test" , "run android --debug"),
        ("Android - build only" , "build android --debug"),
        ("iOS - test" , "run ios --debug"),
        ("iOS - build only" , "build ios --debug"),
        ("Firefox App - test" , "run firefox --debug"),
        ("Firefox App - build only" , "build firefox --debug"),
    ]
    flambe_target = ("Flash - run", "run flash --debug")

    def __init__(self) :

        self.args = []
        self.main = None
        self.target = None
        self.output = None
        self.hxml = None
        self.nmml = None
        self.yaml = None
        self.classpaths = []
        self.libs = []
        self.classes = None
        self.packages = None
        self.libClasses = None
        self.libPacks = None
        self.openfl = False
        self.lime = False
        self.cwd = None

    def __eq__(self,other) :
        return self.__dict__ == other.__dict__

    def __cmp__(self,other) :
        return self.__dict__ == other.__dict__

    def is_valid(self) :
        if self.hxml is not None and self.target is None and self.yaml is None and self.nmml is None :
            return False
        if self.main is None and self.output is None :
            return False;
        return True;

    def to_string(self) :
        if not self.is_valid() :
            return "Invalid Build"

        out = self.main
        if self.output is not None :
            out = os.path.basename(self.output)

        main = self.main
        if main is None :
            main = "[no main]"

        if self.openfl :
            return "{out} (openfl / {target})".format(self=self, out=out, target=HaxeBuild.nme_target[0]);
        elif self.lime :
            return "{out} (lime / {target})".format(self=self, out=out, target=HaxeBuild.nme_target[0]);
        elif self.nmml is not None:
            return "{out} (NME / {target})".format(self=self, out=out, target=HaxeBuild.nme_target[0]);
        elif self.yaml is not None:
            return "{out} (Flambe / {target})".format(self=self, out=out, target=HaxeBuild.flambe_target[0]);
        else:
            if self.target == "--interp" :
                return "{main} (interp)".format(main=main);
            if self.target == "--run" :
                return "{main} (run)".format(main=main);

            return "{main} ({target}:{out})".format(self=self, out=out, main=main, target=self.target);
        #return "{self.main} {self.target}:{out}".format(self=self, out=out);

    def make_hxml( self ) :
        outp = "# Autogenerated "+self.hxml+"\n\n"
        outp += "# "+self.to_string() + "\n"
        outp += "-main "+ self.main + "\n"
        for a in self.args :
            outp += " ".join( list(a) ) + "\n"

        d = os.path.dirname( self.hxml ) + "/"

        # relative paths
        outp = outp.replace( d , "")
        outp = outp.replace( "-cp "+os.path.dirname( self.hxml )+"\n", "")

        outp = outp.replace("--no-output" , "")
        outp = outp.replace("-v" , "")

        #outp = outp.replace("dummy" , self.main.lower() )

        #print( outp )
        return outp.strip()

    def is_temp( self ) :
        return not os.path.exists( self.hxml )

    def get_types( self ) :
        cwd = self.cwd
        if cwd is None :
            cwd = os.path.dirname( self.hxml )

        if self.libClasses is None or self.libPacks is None :
            classes = []
            packs = []
            cp = []

            for lib in self.libs :
                if lib is None :
                    continue
                c, p = HaxeComplete.inst.extract_types(
                    os.path.join( cwd , lib.path ),
                    cache_name = '%s_%s.cache' % (lib.name, lib.version) )
                classes.extend( c )
                packs.extend( p )

            self.libClasses = classes;
            self.libPacks = packs;

        classes = []
        packs = []
        cp = self.classpaths

        for path in cp :
            c, p = HaxeComplete.inst.extract_types( os.path.join( cwd , path ) )
            classes.extend( c )
            packs.extend( p )

        classes.extend(self.libClasses)
        packs.extend(self.libPacks)

        classes.sort()
        packs.sort()

        self.classes = classes;
        self.packs = packs;

        return self.classes, self.packs

    def get_classpath(self, view):
        filepath = view.file_name()

        buildpath = self.hxml
        if buildpath is None:
            buildpath = self.nmml
        if buildpath is None:
            buildpath = self.yaml

        builddir = os.path.dirname(buildpath)

        abscps = []
        for cp in self.classpaths:
            if os.path.isabs(cp):
                abscps.append(cp)
            else:
                abscps.append(
                    os.path.normpath(os.path.join(builddir, cp)))

        for cp in abscps:
            if cp in filepath:
                return cp

        return None



class HaxeDisplayCompletion( sublime_plugin.TextCommand ):

    def show_auto_complete(self):
        view = self.view

        HaxeComplete.inst.force_display_completion = True
        HaxeComplete.inst.type_completion_only = self.type_completion
        view.run_command('auto_complete', {
            'api_completions_only': True,
            'disable_auto_insert': True,
            'next_completion_if_showing': False
        })
        HaxeComplete.inst.force_display_completion = False
        HaxeComplete.inst.type_completion_only = False

    def run(self, edit, type_completion=False, hide=False):
        view = self.view
        self.type_completion = type_completion
        if hide:
            view.run_command('hide_auto_complete')
            sublime.set_timeout(self.show_auto_complete, 100)
        else:
            self.show_auto_complete()


class HaxeInsertCompletion( sublime_plugin.TextCommand ):

    def run( self , edit ) :
        #print("insert completion")
        view = self.view

        view.run_command( "insert_best_completion" , {
            "default" : ".",
            "exact" : True
        } )

class HaxeSaveAllAndBuild( sublime_plugin.TextCommand ):
    def run( self , edit ) :
        complete = HaxeComplete.inst
        view = self.view
        view.window().run_command("save_all")
        complete.run_build( view )

class HaxeRunBuild( sublime_plugin.TextCommand ):
    def run( self , edit ) :
        complete = HaxeComplete.inst
        view = self.view

        complete.run_build( view )


class HaxeSelectBuild( sublime_plugin.TextCommand ):
    def run( self , edit , all_views = False ) :
        complete = HaxeComplete.inst
        view = self.view

        complete.select_build( view , all_views )


class HaxeComplete( sublime_plugin.EventListener ):

    #folder = ""
    #buildArgs = []
    currentBuild = None
    selectingBuild = False
    builds = []
    haxe_settings_file = 'Preferences.sublime-settings'

    currentCompletion = {
        "inp" : None,
        "outp" : None
    }

    classpathExclude = ['.git','_std']
    classpathDepth = 2

    stdPaths = []
    stdPackages = []
    #stdClasses = ["Void","Float","Int","UInt","Null","Bool","Dynamic","Iterator","Iterable","ArrayAccess"]
    stdClasses = []
    stdCompletes = []

    visibleCompletionList = [] # This will contain the list of visible completions, if there is one.

    panel = None
    serverMode = False
    serverProc = None
    serverPort = 6000

    compilerVersion = 2
    inited = False

    def __init__(self):
        #print("init haxecomplete")
        HaxeComplete.inst = self
        self.build_cache = {}
        self.force_display_completion = False
        self.type_completion_only = False
        self.selected_build_id_map = {}

    def __del__(self) :
        self.stop_server()


    def extract_types( self , path , depth = 0 , cache_name = None ) :

        classes = []
        packs = []
        hasClasses = False

        if cache_name is not None:
            view = sublime.active_window().active_view()
            if view.settings().get('haxe_use_cache', True):
                cache_str = cache(cache_name)
                if cache_str is not None:
                    spl = cache_str.split(';')
                    classes = spl[0].split(',')
                    packs = spl[1].split(',')
                    return classes, packs

        #print(path)
        if not os.path.exists( path ) :
            print('Warning: path %s doesn´t exists.'%path);
            return classes, packs

        for fullpath in glob.glob( os.path.join(path,"*.hx") ) :
            f = os.path.basename(fullpath)

            cl, ext = os.path.splitext( f )

            if cl not in HaxeComplete.stdClasses:
                s = codecs.open( os.path.join( path , f ) , "r" , "utf-8" , "ignore" )
                src = comments.sub( "" , s.read() )

                clPack = "";
                for ps in packageLine.findall( src ) :
                    clPack = ps

                if clPack == "" :
                    packDepth = 0
                else:
                    packDepth = len(clPack.split("."))

                for decl in typeDecl.findall( src ):
                    t = decl[1]
                    params = decl[2]

                    if( packDepth == depth ) : # and t == cl or cl == "StdTypes"
                        if t == cl or cl == "StdTypes":
                            classes.append( t + params )
                        else:
                            classes.append( cl + "." + t + params )

                        hasClasses = True


        if hasClasses or depth <= self.classpathDepth :

            for f in os.listdir( path ) :

                cl, ext = os.path.splitext( f )

                if os.path.isdir( os.path.join( path , f ) ) and f not in self.classpathExclude :
                    packs.append( f )
                    subclasses,subpacks = self.extract_types( os.path.join( path , f ) , depth + 1 )
                    for cl in subclasses :
                        classes.append( f + "." + cl )


        classes.sort()
        packs.sort()

        if cache_name is not None:
            view = sublime.active_window().active_view()
            if view.settings().get('haxe_use_cache', True):
                cache_str = ';'.join((','.join(classes), ','.join(packs)))
                cache(cache_name, cache_str)

        return classes, packs

    def on_post_save( self , view ) :
        if view.score_selector(0,'source.hxml') > 0:
            self.clear_build(view)

    def on_activated( self , view ) :
        return self.on_open_file( view )

    def on_load( self, view ) :
        return self.on_open_file( view )

    def on_open_file( self , view ) :
        if view.is_loading() :
            return;

        if view.window() is None:
            return

        if view.score_selector(0,'source.haxe.2') > 0 :
            HaxeCreateType.on_activated( view )
        elif view.score_selector(0,'source.hxml,source.erazor,source.nmml') == 0:
            return

        self.init_plugin( view )
        # HaxeProjects.determine_type()

        self.extract_build_args( view )
        self.get_build( view )
        self.generate_build( view )
        highlight_errors( view )

    def on_pre_save( self , view ) :
        if view.score_selector(0,'source.haxe.2') == 0 :
            return []

        fn = view.file_name()

        if fn is not None :
            path = os.path.dirname( fn )
            if not os.path.isdir( path ) :
                os.makedirs( path )

    def __on_modified( self , view ):
        win = sublime.active_window()
        if win is None :
            return None

        isOk = ( win.active_view().buffer_id() == view.buffer_id() )
        if not isOk :
            return None

        sel = view.sel()
        caret = 0
        for s in sel :
            caret = s.a

        if caret == 0 :
            return None

        if view.score_selector(caret,"source.haxe") == 0 or view.score_selector(caret,"string,comment,keyword.control.directive.conditional.haxe.2") > 0 :
            return None

        src = view.substr(sublime.Region(0, view.size()))
        ch = src[caret-1]
        #print(ch)
        if ch not in ".(:, " :
            view.run_command("haxe_display_completion")
        #else :
        #   view.run_command("haxe_insert_completion")


    def generate_build(self, view) :

        fn = view.file_name()

        if fn is not None and self.currentBuild is not None and fn == self.currentBuild.hxml and view.size() == 0 :
            view.run_command("insert_snippet",{
                "contents" : self.currentBuild.make_hxml()
            })


    def select_build( self , view , all_views = False ) :
        scopes = view.scope_name(view.sel()[0].end()).split()

        if 'source.hxml' in scopes:
            view.run_command("save")

        self.extract_build_args( view , True , all_views )


    def find_nmml( self, folder ) :
        nmmls = glob.glob( os.path.join( folder , "*.nmml" ) )
        nmmls += glob.glob( os.path.join( folder , "*.xml" ) )
        nmmls += glob.glob( os.path.join( folder , "*.hxp" ) )
        nmmls += glob.glob( os.path.join( folder , "*.lime" ) )

        for build in nmmls:
            # yeah...
            if not os.path.exists( build ) :
                continue

            f = codecs.open( build , "r+", "utf-8" , "ignore" )
            raw = f.read()

            if build in self.build_cache and \
                    self.build_cache[build].raw == raw:
                currentBuild = self.build_cache[build].build
                if currentBuild.main is not None :
                    self.add_build( currentBuild )
                continue

            currentBuild = HaxeBuild()
            currentBuild.hxml = build
            currentBuild.nmml = build
            currentBuild.openfl = build.endswith("xml")
            currentBuild.lime = build.endswith("lime")
            buildPath = os.path.dirname(build)

            self.build_cache[build] = BuildCache(build, raw, currentBuild, None)

            outp = "NME"
            is_hxp = build.endswith("hxp")
            if is_hxp:
                currentBuild.main = 'hxp'
                outp = 'Lime/OpenFl'
                currentBuild.lime = True

            lines = raw.splitlines()
            for l in lines:
                if len(l) > 200:
                    continue
                if is_hxp:
                    continue
                m = extractTag.search(l)
                if not m is None:
                    #print(m.groups())
                    tag = m.group(1)
                    name = m.group(3)
                    if (tag == "app"):
                        currentBuild.main = name
                        currentBuild.args.append( ("-main" , name) )
                        mFile = re.search("\\b(file|title)=\"([a-z0-9_-]+)\"", l, re.I)
                        if not mFile is None:
                            outp = mFile.group(2)
                    elif (tag == "haxelib"):
                        currentBuild.libs.append( HaxeLib.get( name ) )
                        currentBuild.args.append( ("-lib" , name) )
                    elif (tag == "haxedef"):
                        currentBuild.args.append( ("-D", name) )
                    elif (tag == "classpath" or tag == "source"):
                        currentBuild.classpaths.append( os.path.join( buildPath , name ) )
                        currentBuild.args.append( ("-cp" , os.path.join( buildPath , name ) ) )
                else: # NME 3.2
                    mPath = re.search("\\bpath=\"([a-z0-9_-]+)\"", l, re.I)
                    if not mPath is None:
                        #print(mPath.groups())
                        path = mPath.group(1)
                        currentBuild.classpaths.append( os.path.join( buildPath , path ) )
                        currentBuild.args.append( ("-cp" , os.path.join( buildPath , path ) ) )

            outp = os.path.join( folder , outp )

            if currentBuild.openfl or currentBuild.lime :
                if self.compilerVersion >= 3 :
                    currentBuild.target = "swf"
                else :
                    currentBuild.target = "swf9"

            else :
                currentBuild.target = "cpp"
                currentBuild.args.append( ("--remap", "flash:nme") )
            #currentBuild.args.append( ("-cpp", outp) )
            currentBuild.output = outp
            currentBuild.args.append( ("-"+currentBuild.target, outp) )

            if currentBuild.main is not None :
                self.add_build( currentBuild )

    def find_yaml( self, folder ) :
        yamls = glob.glob( os.path.join( folder , "flambe.yaml") )

        for build in yamls :

            # yeah...
            if not os.path.exists( build ) :
                continue

            currentBuild = HaxeBuild()
            currentBuild.hxml = build
            currentBuild.yaml = build
            currentBuild.cwd = os.path.dirname( build )
            currentBuild.output = "Flambe"

            res, err = runcmd(
                ["flambe","--config" , build, "haxe-flags"] )
            lines = res.split('\n')

            i, n = 0, len(lines)
            while i < n:
                if lines[i] == '-lib':
                    i += 1
                    lib = HaxeLib.get(lines[i])
                    if lib is not None:
                        currentBuild.libs.append(lib)
                i += 1

            self.add_build( currentBuild )


    def read_hxml( self, build ) :
        #print("Reading build " + build );

        def _read_hxml( build, builds ) :
            buildPath = os.path.dirname(build);

            spl = build.split("@")
            if( len(spl) == 2 ) :
                buildPath = spl[0]
                build = os.path.join( spl[0] , spl[1] )

            if not os.path.exists( build ) :
                return builds

            if builds:
                currentBuild = builds[-1]
            else:
                currentBuild = HaxeBuild()
                currentBuild.hxml = build
                currentBuild.cwd = buildPath
                builds.append(currentBuild)

            #print( currentBuild )

            with codecs.open( build , "r+" , "utf-8" , "ignore" ) as f:
                lines = f.readlines()
                while lines:
                    l = lines.pop(0)
                    l = l.strip()

                    if l.startswith("#") : # a comment
                        pass

                    elif l.startswith("--next") :
                        currentBuild = HaxeBuild()
                        currentBuild.hxml = build
                        currentBuild.cwd = buildPath
                        builds.append(currentBuild)

                    elif l.startswith("-main") :
                        spl = l.split(" ", 1)
                        if len( spl ) == 2 :
                            currentBuild.main = spl[1]
                            currentBuild.args.append( ( spl[0] , spl[1] ) )
                        else :
                            sublime.status_message( "Invalid build.hxml : no Main class" )

                    elif l.startswith("-lib") :
                        spl = l.split(" ", 1)
                        if len( spl ) == 2 :
                            lib = HaxeLib.get( spl[1] )
                            currentBuild.libs.append( lib )
                            currentBuild.args.append( spl )
                        else :
                            sublime.status_message( "Invalid build.hxml : lib not found" )

                    elif [l for flag in [ "cmd" , "-macro" ] if l.startswith( "-" + flag )] :
                        spl = l.split(" ", 1)
                        currentBuild.args.append( ( spl[0] , spl[1] ) )

                    #elif l.startswith("--connect") and HaxeComplete.inst.serverMode :
                    #   currentBuild.args.append( ( "--connect" , str(self.serverPort) ))

                    elif [l for flag in [
                        "D" ,
                        "swf-version" ,
                        "swf-header",
                        "debug" ,
                        "-no-traces" ,
                        "-flash-use-stage" ,
                        "-gen-hx-classes" ,
                        "-remap" ,
                        "-no-inline" ,
                        "-no-opt" ,
                        "-php-prefix" ,
                        "-js-namespace" ,
                        "-dead-code-elimination" ,
                        "-remap" ,
                        "-php-front" ,
                        "-php-lib",
                        "dce" ,
                        "-js-modern" ,
                        "swf-lib"
                    ] if l.startswith( "-"+flag )]:
                        currentBuild.args.append( l.split(" ", 1) )

                    elif [l for flag in [ "resource" , "xml" , "java-lib" , "net-lib" ] if l.startswith( "-"+flag )] :
                        spl = l.split(" ", 1)
                        outp = os.path.join( buildPath , spl[1] )
                        currentBuild.args.append( (spl[0] , outp) )

                    #print(HaxeBuild.targets)
                    elif [l for flag in HaxeBuild.targets if l.startswith( "-" + flag + " " )] :
                        spl = l.split(" ", 1)
                        #outp = os.path.join( folder , spl[1] )
                        outp = spl[1]
                        #currentBuild.args.append( ("-"+spl[0], outp) )
                        currentBuild.target = spl[0][1:]
                        currentBuild.output = outp
                        currentBuild.args.append( ( spl[0] , outp ) )

                    elif l.startswith( "--interp" ) :
                        currentBuild.target = "--interp"
                        currentBuild.output = ""
                        currentBuild.args.append( ( "--interp", ) )

                    elif l.startswith( "--run" ) :
                        spl = l.split(" ", 1)
                        #outp = os.path.join( folder , spl[1] )
                        outp = spl[1]

                        currentBuild.target = "--run"
                        currentBuild.output = outp
                        currentBuild.main = outp
                        currentBuild.args.append( ( "--run" , outp ) )
                        while lines:
                            l = lines.pop(0).strip()
                            if (not l) or l.startswith("#") : # an empty line or a comment
                                continue
                            currentBuild.args.append( (l,) )

                    elif l.startswith("-cp "):
                        cp = l.split(" ", 1)
                        #view.set_status( "haxe-status" , "Building..." )
                        classpath = cp[1]
                        absClasspath = classpath#os.path.join( buildPath , classpath )
                        currentBuild.classpaths.append( absClasspath )
                        currentBuild.args.append( ("-cp" , absClasspath ) )

                    elif l.endswith(".hxml"):
                        _read_hxml(os.path.join(currentBuild.cwd, l), builds)

                    elif re.match(r'[A-Za-z0-9_\.]+', l): # a haxe class
                        currentBuild.args.append( (l,) )

                    elif l:
                        sublime.status_message("unknown compiler argument: " + l)

                        # maybe there is a new compiler argument that we don't know,
                        # so let's add the argument anyway
                        currentBuild.args.append( (l,) )

            return builds

        builds = _read_hxml(build, [])

        for build in builds:
            if len(build.classpaths) == 0:
                build.classpaths.append( build.cwd )
                build.args.append( ("-cp" , build.cwd ) )

        return [build for build in builds if build.is_valid()]

    def add_build( self , build ) :
        if build in self.builds :
            self.builds.remove( build )

        self.builds.insert( 0, build )

    def find_hxml( self, folder ) :
        hxmls = glob.glob( os.path.join( folder , "*.hxml" ) )

        for build in hxmls:
            for b in self.read_hxml( build ):
                self.add_build( b )


    def find_build_file( self , folder ) :
        self.find_hxml(folder)
        self.find_nmml(folder)
        self.find_yaml(folder)

    def extract_build_args( self , view ,
            forcePanel = False , all_views = False ) :
        #print("extract build args")
        self.builds = []

        fn = view.file_name()
        settings = view.settings()
        win = view.window()
        folder = None
        file_folder = None
        # folder containing the file, opened in window
        project_folder = None
        win_folders = []
        folders = []

        if fn is not None :
            file_folder = folder = os.path.dirname(fn)

        # find window folder containing the file
        if win is not None :
            win_folders = win.folders()
            for f in win_folders:
                if f + os.sep in fn :
                    project_folder = folder = f

        # extract build files from project
        build_files = view.settings().get('haxe_builds')
        if build_files is not None :
            for build in build_files :
                if( int(sublime.version()) > 3000 ) and win is not None :
                    # files are relative to project file name
                    proj = win.project_file_name()
                    if( proj is not None ) :
                        proj_path = os.path.dirname( proj )
                        build = os.path.join( proj_path , build )

                for b in self.read_hxml( build ) :
                    self.add_build( b )

        else :

            crawl_folders = []

            # go up all folders from file to project or root
            if file_folder is not None :
                f = os.path.normpath(file_folder)
                prev = None
                while prev != f and ( project_folder is None or project_folder in f ):
                    crawl_folders.append( f )
                    prev = f
                    f = os.path.abspath(os.path.join(f, os.pardir))

            # crawl other window folders
            for f in win_folders :
                if f not in crawl_folders :
                    crawl_folders.append( f )

            for f in crawl_folders :
                self.find_build_file( f )

        if len(self.builds) == 1:
            if forcePanel :
                sublime.status_message("There is only one build")

            # will open the build file
            #if forcePanel :
            #   b = self.builds[0]
            #   f = b.hxml
            #   v = view.window().open_file(f,sublime.TRANSIENT)

            self.set_current_build( view , int(0), forcePanel )

        elif len(self.builds) == 0 and forcePanel :
            sublime.status_message("No hxml or nmml file found")

            f = os.path.join(folder,"build.hxml")

            self.currentBuild = None
            self.get_build(view)
            self.currentBuild.hxml = f

            #for whatever reason generate_build doesn't work without transient
            v = view.window().open_file(f,sublime.TRANSIENT)

            self.set_current_build( view , int(0), forcePanel )

        elif len(self.builds) > 1 and forcePanel :
            buildsView = []
            for b in self.builds :
                #for a in b.args :
                #   v.append( " ".join(a) )
                buildsView.append( [b.to_string(), os.path.basename( b.hxml ) ] )

            self.selectingBuild = True
            sublime.status_message("Please select your build")
            show_quick_panel( view.window() , buildsView , lambda i : self.set_current_build(view, int(i), forcePanel, all_views) , sublime.MONOSPACE_FONT )

        elif settings.has("haxe-build-id"):
            self.set_current_build( view , int(settings.get("haxe-build-id")), forcePanel )

        else:
            build_id = 0
            if project_folder is not None:
                if project_folder in self.selected_build_id_map:
                    build_id = self.selected_build_id_map[project_folder]
                else:
                    for i in range(0, len(self.builds)):
                        if project_folder in self.builds[i].hxml:
                            build_id = i
                            break
            self.set_current_build(view, build_id, forcePanel)


    def set_current_build( self , view , id , forcePanel ,
            all_views = False ) :
        if id == -1:
            return

        if id >= len(self.builds) :
            id = 0

        win = view.window()
        project_folder = None
        if forcePanel:
            if win is not None :
                win_folders = win.folders()
                for f in win_folders:
                    if f + os.sep in view.file_name() :
                        project_folder = f
            if project_folder is not None:
                self.selected_build_id_map[project_folder] = id

        if all_views and win is not None and project_folder is not None:
            for v in win.views():
                if v.score_selector(0,'source.haxe.2') == 0:
                    continue
                if project_folder + os.sep not in v.file_name():
                    continue
                v.settings().set( "haxe-build-id" , id )
        else:
            view.settings().set( "haxe-build-id" , id )

        if len(self.builds) > 0 :
            self.currentBuild = self.builds[id]
            view.set_status( "haxe-build" , self.currentBuild.to_string() )
        else:
            #self.currentBuild = None
            view.set_status( "haxe-build" , "No build" )

        self.selectingBuild = False

        if self.currentBuild is not None:

            if forcePanel: # choose target
                if self.currentBuild.nmml is not None:
                    sublime.status_message("Please select a NME target")
                    nme_targets = []
                    for t in HaxeBuild.nme_targets :
                        nme_targets.append( t[0] )

                    show_quick_panel( view.window() , nme_targets, lambda i : self.select_nme_target(i, view))

                elif self.currentBuild.yaml is not None:
                    sublime.status_message("Please select a Flambe target")
                    flambe_targets = []
                    for t in HaxeBuild.flambe_targets :
                        flambe_targets.append( t[0] )

                    show_quick_panel( view.window() , flambe_targets, lambda i : self.select_flambe_target(i, view))
            else:
                if self.currentBuild.nmml is not None:
                    bc = self.build_cache[self.currentBuild.nmml]
                    if HaxeBuild.nme_target and \
                            bc.target != HaxeBuild.nme_target:
                        bc.target = HaxeBuild.nme_target
                        args = self.extract_nme_completion_args(view)
                        if args:
                            self.currentBuild.args = args


    def select_nme_target( self, i, view ):
        if i == -1:
            return

        target = HaxeBuild.nme_targets[i]

        self.haxe_settings.set('haxe_nme_target', i)
        sublime.save_settings(self.haxe_settings_file)

        if self.currentBuild.nmml is not None:
            HaxeBuild.nme_target = target
            view.set_status( "haxe-build" , self.currentBuild.to_string() )

            bc = self.build_cache[self.currentBuild.nmml]
            bc.target = HaxeBuild.nme_target

        args = self.extract_nme_completion_args(view)
        if args:
            self.currentBuild.args = args


    def extract_nme_completion_args(self, view):
        lib = 'nme'
        if self.currentBuild.lime:
            lib = 'lime'
        elif self.currentBuild.openfl:
            lib = 'openfl'
        target = HaxeBuild.nme_target[1].split(" ")[0]

        res, err = runcmd( [
            view.settings().get("haxelib_path" , "haxelib"),
            'run', lib, 'display', self.currentBuild.nmml, target] )

        if err :
            return None

        return [
            (arg,)
            for line in res.split('\n')
            for arg in line.split(' ')
            if arg
            ]

    def select_flambe_target( self , i , view ):
        if i == -1:
            return

        target = HaxeBuild.flambe_targets[i]

        self.haxe_settings.set('haxe_flambe_target', i)
        sublime.save_settings(self.haxe_settings_file)

        if self.currentBuild.yaml is not None:
            HaxeBuild.flambe_target = target
            view.set_status( "haxe-build" , self.currentBuild.to_string() )


    def run_build( self , view ) :

        err, comps, status = self.run_haxe( view )
        view.set_status( "haxe-status" , status )


    def clear_output_panel(self, view) :
        win = view.window()

        self.panel = win.get_output_panel("haxe")

    def panel_output( self , view , text , scope = None ) :
        win = view.window()
        if self.panel is None :
            self.panel = win.get_output_panel("haxe")

        panel = self.panel

        text = datetime.now().strftime("%H:%M:%S") + " " + text;

        edit = panel.begin_edit()
        region = sublime.Region(panel.size(),panel.size() + len(text))
        panel.insert(edit, panel.size(), text + "\n")
        panel.end_edit( edit )

        if scope is not None :
            icon = "dot"
            key = "haxe-" + scope
            regions = panel.get_regions( key );
            regions.append(region)
            panel.add_regions( key , regions , scope , icon )
        #print( err )
        win.run_command("show_panel",{"panel":"output.haxe"})

        return self.panel

    def get_toplevel_completion( self , src , src_dir , build ) :
        cl = []
        comps = [("trace","trace"),("this","this"),("super","super"),("else","else")]

        src = comments.sub("",src)

        localTypes = typeDecl.findall( src )
        for t in localTypes :
            if t[1] not in cl:
                cl.append( t[1] )

        packageClasses, subPacks = self.extract_types( src_dir )
        for c in packageClasses :
            if c not in cl:
                cl.append( c )

        imports = importLine.findall( src )
        imported = []
        for i in imports :
            imp = i[1]
            imported.append(imp)
            #dot = imp.rfind(".")+1
            #clname = imp[dot:]
            #cl.append( imp )
            #print( i )

        #print cl
        buildClasses , buildPacks = build.get_types()

        tarPkg = None
        targetPackages = ["flash","flash9","flash8","neko","js","php","cpp","cs","java","nme"]

        compilerVersion = HaxeComplete.inst.compilerVersion

        if build.target is not None :
            tarPkg = build.target
            if tarPkg == "x":
                tarPkg = "neko"

            # haxe 2
            if tarPkg == "swf9" :
                tarPkg = "flash"

            # haxe 3
            if tarPkg == "swf8" :
                tarPkg = "flash8"

            if tarPkg == "swf" :
                if compilerVersion >= 3 :
                    tarPkg = "flash"
                else :
                    tarPkg = "flash8"

        if not build.openfl and not build.lime and build.nmml is not None or "nme" in HaxeLib.available and HaxeLib.get("nme") in build.libs :
            tarPkg = "nme"
            targetPackages.extend( ["jeash","neash","browser","native"] )

        #print( "tarpkg : " + tarPkg );
        #for c in HaxeComplete.stdClasses :
        #   p = c.split(".")[0]
        #   if tarPkg is None or (p not in targetPackages) or (p == tarPkg) :
        #       cl.append(c)

        cl.extend( imported )
        cl.extend( HaxeComplete.stdClasses )
        cl.extend( buildClasses )
        cl = list(set(cl)) # unique
        cl.sort();

        packs = []
        stdPackages = []
        #print("target : "+build.target)
        for p in HaxeComplete.stdPackages :
            #print(p)
            #if p == "flash9" or p == "flash8" :
            #   p = "flash"
            if tarPkg is None or (p not in targetPackages) or (p == tarPkg) :
                stdPackages.append(p)

        packs.extend( stdPackages )
        packs.extend( buildPacks )
        packs.sort()

        for v in variables.findall(src) :
            comps.append(( v + "\tvar" , v ))

        for f in functions.findall(src) :
            if f not in ["new"] :
                comps.append(( f + "\tfunction" , f ))


        #TODO can we restrict this to local scope ?
        for paramsText in functionParams.findall(src) :
            cleanedParamsText = re.sub(paramDefault,"",paramsText)
            paramsList = cleanedParamsText.split(",")
            for param in paramsList:
                a = param.strip();
                if a.startswith("?"):
                    a = a[1:]

                idx = a.find(":")
                if idx > -1:
                    a = a[0:idx]

                idx = a.find("=")
                if idx > -1:
                    a = a[0:idx]

                a = a.strip()
                cm = (a + "\tvar", a)
                if cm not in comps:
                    comps.append( cm )

        if self.type_completion_only:
            comps = []

        for c in cl :
            #print(c)
            spl = c.split(".")
            #if spl[0] == "flash9" or spl[0] == "flash8" :
            #   spl[0] = "flash"

            top = spl[0]
            #print(spl)

            clname = spl.pop()
            pack = ".".join(spl)
            display = clname

            # remove parameters
            clname = clname.split('<')[0]

            #if pack in imported:
            #   pack = ""

            if pack != "" :
                display += "\t" + pack
            else :
                display += "\tclass"

            spl.append(clname)

            if pack in imported or c in imported :
                cm = ( display , clname )
            else :
                cm = ( display , ".".join(spl) )

            if cm not in comps and tarPkg is None or (top not in targetPackages) or (top == tarPkg) : #( build.target is None or (top not in HaxeBuild.targets) or (top == build.target) ) :
                comps.append( cm )

        if not self.type_completion_only:
            for p in packs :
                cm = (p + "\tpackage",p)
                if cm not in comps :
                    comps.append(cm)

        return comps

    def clear_build( self , view ) :
        self.currentBuild = None
        self.currentCompletion = {
            "inp" : None,
            "outp" : None
        }

    def get_build( self , view ) :

        fn = view.file_name()
        win = view.window()

        if win is None or fn is None :
            return

        if fn is not None and self.currentBuild is None and view.score_selector(0,"source.haxe.2") > 0 :

            src_dir = os.path.dirname( fn )
            src = view.substr(sublime.Region(0, view.size()))

            build = HaxeBuild()
            build.target = "js"

            folder = os.path.dirname(fn)
            folders = win.folders()
            for f in folders:
                if f in fn :
                    folder = f

            pack = []
            for ps in packageLine.findall( src ) :
                if ps == "":
                    continue

                pack = ps.split(".")
                for p in reversed(pack) :
                    spl = os.path.split( src_dir )
                    if( spl[1] == p ) :
                        src_dir = spl[0]

            cl = os.path.basename(fn)

            #if int(sublime.version() < 3000) :
            #    cl = cl.encode('ascii','ignore')

            cl = cl[0:cl.rfind(".")]

            main = pack[0:]
            main.append( cl )
            build.main = ".".join( main )

            build.output = os.path.join(folder,build.main.lower() + ".js")

            build.args.append( ("-cp" , src_dir) )
            build.args.append( ("--no-output",) )
            #build.args.append( ("-main" , build.main ) )

            build.args.append( ( "-" + build.target , build.output ) )
            #build.args.append( ("--no-output" , "-v" ) )

            build.hxml = os.path.join( src_dir , "build.hxml")

            #build.hxml = os.path.join( src_dir , "build.hxml")
            self.currentBuild = build

        if self.currentBuild is not None :
            view.set_status( "haxe-build" , self.currentBuild.to_string() )

        return self.currentBuild


    def run_nme( self, view, build ) :

        settings = view.settings()
        haxelib_path = settings.get("haxelib_path" , "haxelib")

        if build.openfl :
            cmd = [haxelib_path,"run","openfl"]
        elif build.lime :
            cmd = [haxelib_path,"run","lime"]
        else :
            cmd = [haxelib_path,"run","nme"]

        cmd += [ HaxeBuild.nme_target[2], os.path.basename(build.nmml) ]
        target = HaxeBuild.nme_target[1].split(" ")
        cmd.extend(target)

        cmdArgs = {
            "cmd": cmd,
            "env": get_env(),
            "working_dir": os.path.dirname(build.nmml),
            "file_regex": haxeFileRegex #"^([^:]*):([0-9]+): characters [0-9]+-([0-9]+) :.*$"
        }

        # Sublime Text 3+ supports colorizing of the build system output
        if int(sublime.version()) >= 3000:
            cmdArgs["syntax"] = "Packages/Haxe/Support/HaxeResults.hidden-tmLanguage"

        view.window().run_command("exec", cmdArgs)
        return ("" , [], "" )

    def run_flambe( self , view , build ):
        cmd = [ "flambe.cmd" if os.name == "nt" else "flambe" ]

        cmd += HaxeBuild.flambe_target[1].split(" ")

        # Use the build server if available
        buildServerMode = view.settings().get('haxe_build_server_mode', True)
        if self.serverMode and buildServerMode :
            cmd += ["--haxe-server", str(HaxeComplete.inst.serverPort)]

        cmdArgs = {
            "cmd": cmd,
            "env": get_env(),
            "working_dir": build.cwd,
            "file_regex": haxeFileRegex #"^([^:]*):([0-9]+): characters [0-9]+-([0-9]+) :.*$"
        }

        # Sublime Text 3+ supports colorizing of the build system output
        if int(sublime.version()) >= 3000:
            cmdArgs["syntax"] = "Packages/Haxe/Support/HaxeResults.hidden-tmLanguage"

        view.window().run_command("exec", cmdArgs)
        return ("" , [], "" )

    def init_plugin( self , view ) :

        if self.inited :
            return

        self.inited = True

        HaxeLib.scan( view )

        settings = view.settings()
        self.haxe_settings = sublime.load_settings(self.haxe_settings_file)
        haxepath = settings.get("haxe_path","haxe")

        #init selected_build_id_map
        win = view.window()
        if win is not None :
            for v in win.views():
                project_folder = None
                win_folders = win.folders()
                if not v.settings().has('haxe-build-id'):
                    continue

                for f in win_folders:
                    if f + os.sep in v.file_name() :
                        project_folder = f

                if project_folder is not None:
                    self.selected_build_id_map[project_folder] = \
                        int(v.settings().get('haxe-build-id'))

        nme_target_idx = 0
        try:
            nme_target_idx = int(self.haxe_settings.get('haxe_nme_target', 0))
            if nme_target_idx < 0 or \
                    nme_target_idx >= len(HaxeBuild.nme_targets):
                nme_target_idx = 0
        except:
            pass
        HaxeBuild.nme_target = HaxeBuild.nme_targets[nme_target_idx]

        flambe_target_idx = 0
        try:
            flambe_target_idx = int(
                self.haxe_settings.get('haxe_flambe_target', 0))
            if flambe_target_idx < 0 or \
                    flambe_target_idx >= len(HaxeBuild.flambe_targets):
                flambe_target_idx = 0
        except:
            pass
        HaxeBuild.flambe_target = HaxeBuild.flambe_targets[flambe_target_idx]

        out, err = runcmd( [haxepath, "-main", "Nothing", "-v", "--no-output"] )

        _, versionOut = runcmd([haxepath, "-v"])

        m = classpathLine.match(out)
        if m is not None :
            HaxeComplete.stdPaths = set(m.group(1).split(";")) - set([".","./"])

        ver = re.search(haxeVersion , versionOut)

        HaxeComplete.stdClasses = []
        HaxeComplete.stdPackages = []

        use_cache = view.settings().get('haxe_use_cache', True)
        cached_std = None
        cache_filename = None

        if ver is not None :
            self.compilerVersion = float(ver.group(3))

            if self.compilerVersion >= 3 :
                HaxeBuild.targets.append("swf8")
            else :
                HaxeBuild.targets.append("swf9")

            self.serverMode = float(ver.group(3)) * 100 >= 209

            if use_cache:
                cache_filename = 'haxe_%s.cache' % ver.group(2)
                cached_std = cache(cache_filename)
            if cached_std is not None:
                cp = cached_std.split(';')
                HaxeComplete.stdClasses.extend( cp[0].split(',') )
                HaxeComplete.stdPackages.extend( cp[1].split(',') )

        if cached_std is None:
            for p in HaxeComplete.stdPaths :
                #print("std path : "+p)
                if len(p) > 1 and os.path.exists(p) and os.path.isdir(p):
                    classes, packs = self.extract_types( p )
                    HaxeComplete.stdClasses.extend( classes )
                    HaxeComplete.stdPackages.extend( packs )

            if cache_filename is not None and use_cache:
                cached_std = ';'.join(
                    (','.join(HaxeComplete.stdClasses),
                    ','.join(HaxeComplete.stdPackages)))
                cache(cache_filename, cached_std)

        buildServerMode = settings.get('haxe_build_server_mode', True)
        completionServerMode = settings.get('haxe_completion_server_mode',True)

        self.serverMode = self.serverMode and (buildServerMode or completionServerMode)

        self.start_server( view )

    def start_server( self , view = None ) :
        #self.stop_server()
        if self.serverMode and self.serverProc is None :
            try:
                # env = os.environ.copy()
                merged_env = get_env(True)

                if view is not None :
                    haxepath = view.settings().get("haxe_path" , "haxe")

                self.serverPort+=1
                cmd = [haxepath , "--wait" , str(self.serverPort) ]
                print("Starting Haxe server on port "+str(self.serverPort))

                #self.serverProc = Popen(cmd, env=env , startupinfo=STARTUP_INFO)
                self.serverProc = Popen(cmd, env = merged_env, startupinfo=STARTUP_INFO)
                self.serverProc.poll()

            except(OSError, ValueError) as e:
                err = u'Error starting Haxe server %s: %s' % (" ".join(cmd), e)
                sublime.error_message(err)

    def stop_server( self ) :

        if self.serverProc is not None :
            self.serverProc.terminate()
            self.serverProc.kill()
            self.serverProc.wait()

        self.serverProc = None
        del self.serverProc


    def run_haxe( self, view , display = None, haxe_args = None) :

        self.init_plugin( view )

        build = self.get_build( view )
        settings = view.settings()

        autocomplete = display is not None

        if not autocomplete and build is not None:
            if build.nmml is not None :
                return self.run_nme( view, build )
            if build.yaml is not None :
                return self.run_flambe( view , build )

        fn = view.file_name()
        if fn is None :
            return

        comps = []
        args = []


        cwd = build.cwd
        if cwd is None :
            cwd = os.path.dirname( build.hxml )



        buildServerMode = settings.get('haxe_build_server_mode', True)
        completionServerMode = settings.get('haxe_completion_server_mode',True)

        if self.serverMode and (
                    ( completionServerMode and autocomplete ) or
                    ( buildServerMode and not autocomplete )
                ) and (
                    not display or 'serverMode' not in display or
                    display['serverMode'] ):
            args.append(("--connect" , str(HaxeComplete.inst.serverPort)))
        args.append(("--cwd" , cwd ))
        #args.append( ("--times" , "-v" ) )

        if not autocomplete :
            pass
            #args.append( ("--times" , "-v" ) )
        else:

            display_arg = display["filename"] + "@" + str( display["offset"] )
            if display["mode"] is not None :
                display_arg += "@" + display["mode"]

            args.append( ("--display", display_arg ) )
            args.append( ("-D", "st_display" ) )

            if build.yaml is not None :
                # Call out to `flambe haxe-flags` for Flambe completion
                res, err = runcmd( ["flambe","--config" , build.yaml, "haxe-flags"] )
                if err :
                    print("Flambe completion error: " + err)
                else:
                    args.extend([
                        (arg,)
                        for line in res.split('\n')
                        for arg in line.split(' ')
                        if arg
                        ])
            else:
                args.append( ("--no-output",) )
                output = build.output
                if output is None :
                    output = "no-output"
                #args.append( ("-cp" , plugin_path ) )
                #args.append( ("--macro" , "SourceTools.complete()") )

        args.extend( build.args )

        if haxe_args is not None:
            args.extend( haxe_args )

        haxepath = settings.get( 'haxe_path' , 'haxe' )
        cmd = [haxepath]
        for a in args :
            cmd.extend( list(a) )

        #
        # TODO: replace runcmd with run_command('exec') when possible (haxelib, maybe build)
        #
        if not autocomplete :
            encoded_cmd = []
            for c in cmd :
                #if isinstance( c , unicode) :
                #   encoded_cmd.append( c.encode('utf-8') )
                #else :
                    encoded_cmd.append( c )

            #print(encoded_cmd)

            env = get_env()

            view.window().run_command("haxe_exec", {
                "cmd": encoded_cmd,
                "working_dir": cwd,
                "file_regex": haxeFileRegex,
                "env" : env
            })
            return ("" , [], "" )


        # print(" ".join(cmd))
        res, err = runcmd( cmd, "" )

        if not autocomplete :
            self.panel_output( view , " ".join(cmd) )


        status = ""

        #print(err)
        hints = []
        fields = []
        msg = ""
        tree = None
        pos = None

        commas = 0
        if display["commas"] is not None :
            commas = display["commas"]

        mode = display["mode"]

        if int(sublime.version()) >= 3000 :
            x = "<root>"+err+"</root>"
        else :
            x = "<root>"+err.encode("ASCII",'ignore')+"</root>"

        try :
            tree = ElementTree.XML(x);

        except Exception as e :
            print(e)
            print("invalid xml")

        if tree is not None :
            for i in tree.getiterator("type") :
                hint = i.text.strip()
                params, ret = parse_sig(hint)

                if mode == "type":
                    hint = ret
                    if params:
                        hint = ','.join(params)
                        hint = '(%s):%s' % (hint, ret)
                    return hint

                msg = "";

                if params is not None and commas >= len(params) :
                    if commas == 0 or hint == "Dynamic" :
                        msg = hint + ": No autocompletion available"
                        #view.window().run_command("hide_auto_complete")
                        #comps.append((")",""))
                    else :
                        msg =  "Too many arguments."
                else :
                    if params is None:
                        pass
                    else:
                        hints = params[commas:]
                        #print(hints)
                        if len(hints) == 0 :
                            msg = "Void"
                        else :
                            msg = ", ".join(hints)

            status = msg

            # This will attempt to get the full name of what we're trying to complete.
            # E.g. we type in self.blarg.herp(), this will get "self.blarg".
            fn_name = self.get_current_fn_name(view, view.sel()[0].end())

            pos = tree.findtext("pos")
            li = tree.find("list")

            if li is None:
                li = tree.find("il")

            if li is not None :

                pos = li.findtext("pos")

                for i in li.getiterator("i"):
                    name = i.get("n")
                    if name is None:
                        name = i.text

                    t = i.find("t")
                    if t is not None:
                        sig = t.text
                    else:
                        sig = i.get("t")

                    # if sig is None:
                    #     sig = i.get("p")

                    d = i.find("d")
                    if d is not None:
                        doc = d.text
                    else:
                        doc = "No Doc"

                    #if doc is None: doc = "No documentation found."
                    insert = name
                    hint = name
                    doc_data = { 'hint' : name , 'doc' : doc }
                    documentationStore[fn_name + "." + name] = doc_data

                    if sig is not None :

                        params, ret = parse_sig(sig)
                        fields.append((name, params, ret))

                        if params is not None :
                            cm = name
                            hint = name + "( " + " , ".join( params ) + " )\t" + ret
                            doc_data['hint'] = hint # update before compacting

                            if len(hint) > 40: # compact arguments
                                hint = compactFunc.sub("(...)", hint);
                            insert = cm
                        else :
                            hint = name + "\t" + ret
                            doc_data['hint'] = hint
                    else :
                        if re.match("^[A-Z]",name ) :
                            hint = name + "\tclass"
                        else :
                            hint = name + "\tpackage"
                        doc_data['hint'] = hint

                    #if doc is not None :
                    #   hint += "\t" + doc
                    #   print(doc)

                    if len(hint) > 40: # compact return type
                        m = compactProp.search(hint)
                        if not m is None:
                            hint = compactProp.sub(": " + m.group(1), hint)

                    comps.append( ( hint, insert ) )

        if len(hints) == 0 and len(comps) == 0:
            err = re.sub( u"\(display(.*)\)" ,"",err)

            lines = err.split("\n")
            l = lines[0].strip()

            if len(l) > 0 and status == "":
                if l == "<list>" or l == "<type>":
                    status = "No autocompletion available"
                elif not re.match( haxeFileRegex , l ):
                    status = l
                else :
                    status = ""

            extract_errors( err, cwd )
            highlight_errors( view, 5000 )

        # print(comps)
        if mode == "type":
            return None # this should have returned earlier

        if mode == "position":
            return pos

        return ( err, comps, status, hints, fields )

    def on_query_completions(self, view, prefix, locations):
        
        scope = view.scope_name(locations[0])
        is_haxe = 'source.haxe.2' in scope
        is_hxml = 'source.hxml' in scope
        comps = []

        #print(scope)

        if not self.force_display_completion and \
                not view.settings().get('haxe_auto_complete', True):
            return comps

        if not is_haxe and not is_hxml:
            return comps

        offset = locations[0] - len(prefix)

        if offset == 0 :
            return comps

        if 'keyword.control.directive.conditional.haxe.2' in scope or \
                'meta.control.directive.conditional.haxe.2' in scope or \
                'string' in scope or \
                'comment' in scope:
            return comps

        if is_hxml :
            comps = self.get_hxml_completions( view , offset )
        elif is_haxe :
            if view.file_name().endswith(".hxsl") :
                comps = self.get_hxsl_completions( view , offset )
            else :
                comps,hints = self.get_haxe_completions( view , offset )

        return comps


    def save_temp_file( self , view , force=False ) :
        if not view.is_dirty() and not force:
            return None

        fn = view.file_name()

        tdir = os.path.dirname(fn)
        temp = os.path.join( tdir , os.path.basename( fn ) + ".tmp" )

        src = view.substr(sublime.Region(0, view.size()))

        if not os.path.exists( tdir ):
            os.mkdir( tdir )

        if os.path.exists( fn ):
            if os.path.exists( temp ):
                if os.stat( temp ).st_mode & stat.S_IWRITE == 0:
                    os.chmod( temp , os.stat( temp ).st_mode | stat.S_IWRITE )
                shutil.copy2( temp , fn )
                os.remove( temp )
            # copy saved file to temp for future restoring
            shutil.copy2( fn , temp )

            if os.stat( fn ).st_mode & stat.S_IWRITE == 0:
                os.chmod( fn , os.stat( fn ).st_mode | stat.S_IWRITE )
        # write current source to file
        f = codecs.open( fn , "wb" , "utf-8" , "ignore" )
        f.write( src )
        f.close()

        return temp

    def clear_temp_file( self , view , temp ) :
        if temp is None:
            return

        fn = view.file_name()

        if os.path.exists( temp ) :
            if os.stat( temp ).st_mode & stat.S_IWRITE == 0:
                os.chmod( temp , os.stat( temp ).st_mode | stat.S_IWRITE )

            shutil.copy2( temp , fn )
            # os.chmod( temp, stat.S_IWRITE )
            os.remove( temp )
        else:
            # fn didn't exist in the first place, so we remove it
            os.remove( fn )

    def get_current_fn_name(self, view, offset):
        nonfunction_chars = "\t -=+{}[];':\"?/><,!@#$%^&*()"
        source = view.substr(sublime.Region(0, view.size()))
        source = source[:offset-1]

        closest_nonfunction_char_idx = -1

        for ch in nonfunction_chars:
            idx = source.rfind(ch)
            if idx > closest_nonfunction_char_idx:
                closest_nonfunction_char_idx = idx

        fn_name = source[closest_nonfunction_char_idx + 1:]
        return fn_name


    def get_haxe_completions( self , view , offset , ignoreTopLevel=False ):
        # print("OFFSET");
        # print(offset);
        src = view.substr(sublime.Region(0, view.size()))
        fn = view.file_name()
        src_dir = os.path.dirname(fn)

        if fn is None :
            return

        hints = []
        show_hints = True

        #find actual autocompletable char.
        toplevelComplete = False
        userOffset = completeOffset = offset
        prev = src[offset-1]
        commas = 0
        comps = []
        #print("prev : "+prev)
        if prev not in "(." :
            fragment = view.substr(sublime.Region(0,offset))
            prevDot = fragment.rfind(".")
            prevPar = fragment.rfind("(")
            prevComa = fragment.rfind(",")
            prevColon = fragment.rfind(":")
            prevBrace = fragment.rfind("{")
            prevSymbol = max(prevDot,prevPar,prevComa,prevBrace,prevColon)

            if prevSymbol == prevComa:
                closedPars = 0
                closedBrackets = 0
                closedSquares = 0

                for i in range( prevComa , 0 , -1 ) :
                    c = src[i]

                    if c == "]" :
                        closedSquares += 1
                    elif c == "[" :
                        closedSquares -= 1
                    elif c == ")" :
                        closedPars += 1
                    elif c == "(" :
                        if closedPars < 1 :
                            completeOffset = i+1
                            break
                        else :
                            closedPars -= 1
                    elif c == "," :
                        if closedPars == 0 and closedBrackets == 0 and closedSquares == 0:
                            commas += 1
                    elif c == "{" : # TODO : check for { ... , ... , ... } to have the right comma count
                        closedBrackets -= 1
                        if closedBrackets < 0 :
                            commas = 0

                    elif c == "}" :
                        closedBrackets += 1

                #print("commas : " + str(commas))
                #print("closedBrackets : " + str(closedBrackets))
                #print("closedPars : " + str(closedPars))
                if closedBrackets < 0 or closedSquares < 0 :
                    show_hints = False
            else :
                completeOffset = max( prevDot + 1, prevPar + 1 , prevColon + 1 )
                skipped = src[completeOffset:offset]
                toplevelComplete = (skipped == '' or skippable.search( skipped ) is None) and inAnonymous.search( skipped ) is None

        completeChar = src[completeOffset-1]
        userChar = src[userOffset-1]

        inControlStruct = controlStruct.search( src[0:completeOffset] ) is not None

        toplevelComplete = toplevelComplete or ( completeChar in ":(," and userChar not in ":(," ) or inControlStruct
        if ignoreTopLevel:
            toplevelComplete = False

        mode = None

        if( toplevelComplete ) :
            mode = "toplevel"
            offset = userOffset
        else :
            offset = completeOffset

        if not toplevelComplete and src[offset-1]=="." and src[offset-2] in ".1234567890" :
            #comps.append(("... [iterator]",".."))
            comps.append((".","."))

        #if toplevelComplete and (inControlStruct or completeChar not in "(,") :
        #    return comps,hints

        inp = (fn,offset,commas,src[0:offset-1],mode,self.type_completion_only)
        if (self.currentCompletion["inp"] is None or
                inp != self.currentCompletion["inp"]) :
            ret = ''
            status = ''
            hints = []
            haxeComps = []

            if not self.type_completion_only:
                temp = self.save_temp_file( view )
                byte_offset = len(codecs.encode(src[0:offset], "utf-8"))
                ret , haxeComps , status , hints , _ = self.run_haxe( view , { "filename" : fn , "offset" : byte_offset , "commas" : commas , "mode" : mode })
                self.clear_temp_file( view , temp )

            if (toplevelComplete and len(haxeComps) == 0 or
                    self.type_completion_only):
                haxeComps = self.get_toplevel_completion(
                    src , src_dir , self.get_build( view ) )

            if (toplevelComplete or completeChar not in "(," or
                    self.type_completion_only):
                comps = haxeComps

            self.currentCompletion["outp"] = (ret,comps,status,hints)
        else :
            ret, comps, status , hints = self.currentCompletion["outp"]

        self.currentCompletion["inp"] = inp

        #print(ret)
        #print(status)
        #print(status)

        view.set_status( "haxe-status", status )

        #sublime.status_message("")
        if not show_hints :
            hints = []

        self.visibleCompletionList = comps
        return comps,hints

    def get_hxsl_completions( self , view , offset ) :
        comps = []
        for t in ["Float","Float2","Float3","Float4","Matrix","M44","M33","M34","M43","Texture","CubeTexture","Int","Color","include"] :
            comps.append( ( t , "hxsl Type" ) )
        return comps

    def get_hxml_completions( self , view , offset ) :
        src = view.substr(sublime.Region(0, offset))
        currentLine = src[src.rfind("\n")+1:offset]
        m = libFlag.match( currentLine )
        if m is not None :
            return HaxeLib.get_completions()
        else :
            return []

    def savetotemp( self, path, src ):
        f = tempfile.NamedTemporaryFile( delete=False )
        f.write( src )
        return f


class HaxeShowDocumentation( sublime_plugin.TextCommand ) :
    def run( self , edit ) :

        view = self.view
        complete = HaxeComplete.inst
        sel = view.sel()[0]

        # [('ID\tInt', 'ID'), ('_acceleration\tflixel.util.FlxPoint', '_acceleration'), ('_angleChanged\tBool', '_angleChanged'),
        current_function = complete.get_current_fn_name(view, sel.end() + 1)
        function_qualifications = current_function[:current_function.rfind(".")] + "." # If we have something like foo.bar.baz, this will return just foo.bar.
        current_function = current_function[current_function.rfind(".") + 1:] # And this will return baz.

        # Find what the autocompletion box is likely autocompleting to.

        possible_function_names = [x[0].split("\t")[0] for x in complete.visibleCompletionList]
        possible_function_names = [(x[:x.find("(")] if x.find("(") != -1 else x) for x in possible_function_names]

        matching_function_names = []

        for x in range(0, len(current_function)):
            smaller_name = current_function[:-x] if x != 0 else current_function # first try quux, then quu, then qu, then q. the if/else is a weird special case of slice notation.

            matching_function_names = [fn for fn in possible_function_names if fn.startswith(smaller_name)]

            if len(matching_function_names) > 0: break

        if len(matching_function_names) == 0: return

        best_match = matching_function_names[0]

        self.show_documentation(function_qualifications + best_match, edit)

    # Actually display the documentation in the documentation window.
    def show_documentation(self, fn_name, edit):
        window = sublime.active_window()

        if fn_name not in documentationStore:
            return

        doc_data = documentationStore[fn_name]

        hint = doc_data['hint'].split("\t")

        if( hint[1] == 'class' ) :
            hint_text = hint[1] + " " + hint[0]
        elif( hint[1] == 'package' ) :
            hint_text = hint[1] + " " + hint[0] + ";"
        else:
            hint_text = " : ".join( hint )

        documentation_text = "\n" + hint_text + "\n\n"

        documentation_lines = []

        if doc_data['doc'] is not None :
            documentation_lines = doc_data['doc'].split("\n")
        else :
            documentation_lines = ["","No documentation.",""]

        documentation_text += "/**\n";

        for line in documentation_lines:
            # Strip leading whitespace.
            line = line.strip()

            # Strip out any leading astericks.
            if len(line) > 0 and line[0] == "*":
                line = line[2:]

            documentation_text += line + "\n"

        documentation_text += "**/\n";

        doc_view = window.get_output_panel('haxe-doc');
        doc_view.set_syntax_file('Packages/Haxe/Haxe.tmLanguage')
        doc_view.settings().set('word_wrap', True)
        doc_view.insert(edit, doc_view.size(), documentation_text + "\n")
        window.run_command("show_panel", {"panel": "output.haxe-doc"})


class HaxeExecCommand(ExecCommand):
    def finish(self, *args, **kwargs):
        super(HaxeExecCommand, self).finish(*args, **kwargs)
        outp = self.output_view.substr(sublime.Region(0, self.output_view.size()))
        hc = HaxeComplete.inst
        extract_errors(
            outp, self.output_view.settings().get("result_base_dir") )
        highlight_errors( self.window.active_view() )

    def run(self, cmd = [],  shell_cmd = None, file_regex = "", line_regex = "", working_dir = "",
            encoding = None, env = {}, quiet = False, kill = False,
            word_wrap = True,
            # Catches "path" and "shell"
            **kwargs):


        if int(sublime.version()) >= 3080:
            # clear the text_queue
            self.text_queue_lock.acquire()
            try:
                self.text_queue.clear()
                self.text_queue_proc = None
            finally:
                self.text_queue_lock.release()

        if kill:
            if self.proc:
                self.proc.kill()
                self.proc = None
                self.append_data(None, "[Cancelled]")
            return

        if not hasattr(self, 'output_view'):
            # Try not to call get_output_panel until the regexes are assigned
            self.output_view = self.window.get_output_panel("exec")

        # Default the to the current files directory if no working directory was given
        if (working_dir == "" and self.window.active_view()
                        and self.window.active_view().file_name()):
            working_dir = os.path.dirname(self.window.active_view().file_name())

        self.output_view.settings().set("result_file_regex", file_regex)
        self.output_view.settings().set("result_line_regex", line_regex)
        self.output_view.settings().set("result_base_dir", working_dir)
        self.output_view.settings().set("word_wrap", word_wrap)
        self.output_view.settings().set("line_numbers", False)
        self.output_view.settings().set("gutter", False)
        self.output_view.settings().set("scroll_past_end", False)
        self.output_view.assign_syntax(
            'Packages/Haxe/Support/HaxeResults.hidden-tmLanguage')

        # Call get_output_panel a second time after assigning the above
        # settings, so that it'll be picked up as a result buffer
        self.window.get_output_panel("exec")

        if encoding is None :
            if int(sublime.version()) >= 3000 :
                encoding = sys.getfilesystemencoding()
            else:
                encoding = "utf-8"

        self.encoding = encoding
        self.quiet = quiet

        self.proc = None
        if not self.quiet:
            if int(sublime.version()) >= 3000 :
                print( "Running " + " ".join(cmd) )
            else :
                print( "Running " + " ".join(cmd).encode('utf-8') )

            sublime.status_message("Building")

        show_panel_on_build = sublime.load_settings("Preferences.sublime-settings").get("show_panel_on_build", True)
        if show_panel_on_build:
            self.window.run_command("show_panel", {"panel": "output.exec"})

        merged_env = env.copy()
        if self.window.active_view():
            user_env = self.window.active_view().settings().get('build_env')
            if user_env:
                merged_env.update(user_env)

        # Change to the working dir, rather than spawning the process with it,
        # so that emitted working dir relative path names make sense
        if working_dir != "":
            os.chdir(working_dir)

        self.debug_text = ""
        if shell_cmd:
            self.debug_text += "[shell_cmd: " + shell_cmd + "]\n"
        else:
            self.debug_text += "[cmd: " + str(cmd) + "]\n"
        self.debug_text += "[dir: " + str(os.getcwd()) + "]\n"
        if "PATH" in merged_env:
            self.debug_text += "[path: " + str(merged_env["PATH"]) + "]"
        else:
            self.debug_text += "[path: " + str(os.environ["PATH"]) + "]"

        err_type = OSError
        if os.name == "nt":
            err_type = WindowsError

        try:
            # Forward kwargs to AsyncProcess
            if int(sublime.version()) >= 3080 :
                self.proc = AsyncProcess(cmd, shell_cmd, merged_env, self, **kwargs)

                self.text_queue_lock.acquire()
                try:
                    self.text_queue_proc = self.proc
                finally:
                    self.text_queue_lock.release()
            elif int(sublime.version()) >= 3000 :
                self.proc = AsyncProcess(cmd, None, merged_env, self, **kwargs)
            else :

                self.proc = AsyncProcess([c.encode(sys.getfilesystemencoding()) for c in cmd], merged_env, self, **kwargs)
        except err_type as e:
            self.append_data(None, str(e) + "\n")
            self.append_data(None, "[cmd:  " + str(cmd) + "]\n")
            self.append_data(None, "[dir:  " + str(os.getcwdu()) + "]\n")
            if "PATH" in merged_env:
                self.append_data(None, "[path: " + str(merged_env["PATH"]) + "]\n")
            else:
                self.append_data(None, "[path: " + str(os.environ["PATH"]) + "]\n")
            if not self.quiet:
                self.append_data(None, "[Finished]")


    def is_visible():
        return false

    def on_data(self, proc, data):
        if int(sublime.version()) >= 3080:
            try:
                str = data.decode(self.encoding)
            except:
                str = "[Decode error - output not " + self.encoding + "]\n"
                proc = None

            # Normalize newlines, Sublime Text always uses a single \n separator
            # in memory.
            str = str.replace('\r\n', '\n').replace('\r', '\n')

            self.append_string(proc, str)
        else:
            sublime.set_timeout(functools.partial(self.append_data, proc, data), 0)

    def on_finished(self, proc):
        sublime.set_timeout(functools.partial(self.finish, proc), 1)

class HaxelibExecCommand(ExecCommand):
    def finish(self, *args, **kwargs):
        super(HaxelibExecCommand, self).finish(*args, **kwargs)
        HaxeLib.scan( sublime.active_window().active_view() )

    def is_visible():
        return false
