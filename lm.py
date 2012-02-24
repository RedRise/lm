#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
lm: list movies (or list media)

Copyright (C) 2012  Guillaume Garchery 	(polluxxx@gmail.com)
Copyright (C) 2010  Jérôme Poisson 	(goffi@goffi.org)

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import os
import re
import sys
import time
import imdb
import zlib
import struct
import base64
import codecs
import locale
import logging
import cPickle
import argparse
import xmlrpclib
from difflib import SequenceMatcher
from unicodedata import normalize

# windows terminal coloration
from platform import system
if system().lower()=="windows":
    try:
        import colorama
        colorama.init()
    except:
        pass

# ********** GLOBAL VARIABLES ************************************************
NAME    = 'lm (list movies)'
VERSION	= '0.2'
ABOUT 	= NAME+" v"+VERSION+"""

---
"""+NAME+""" Copyrights:
(C) 2012  Guillaume Garchery 	<http://redrises.blogspot.com>
(C) 2010  Jérôme Poisson 	<http://www.goffi.org>
This program comes with ABSOLUTELY NO WARRANTY;
This is free software, and you are welcome to redistribute it
under certain conditions.
---
This software is a command line tool for listing movies using IMDb metadata
"""

# User agent is essential to request opensubtitles
# be sure to update it before any change
OPENSUBTITLE_USER_AGENT = "lm v2.0"
OPENSUBTITLE_DOMAIN     = "http://api.opensubtitles.org/xml-rpc"

# ********** LOGGiING ********************************************************
class NullHandler(logging.Handler):
    def emit(self, record):
        pass

logger = logging.getLogger("LM UTIL")
logger.setLevel( logging.INFO )
logger.addHandler( NullHandler() )
LOG_FORMAT = "%(asctime)-6s: %(name)s - %(levelname)s - %(message)s"

def consoleLogging( format, level):

    formatter = logging.Formatter( format )
    consoleLogger = logging.StreamHandler()
    consoleLogger.setLevel(level)
    consoleLogger.setFormatter(formatter)
    logging.getLogger().addHandler(consoleLogger)

def fileLogging( format, level, filename):

    formatter = logging.Formatter( format )
    fileLogger = logging.FileHandler(filename=filename, mode="w")
    fileLogger.setLevel(level)
    fileLogger.setFormatter(formatter)
    logging.getLogger().addHandler(fileLogger)

# ********** UTILITY FUNCTIONS ***********************************************
# returns all files in dir (and subdir if recurs==True) filter
# by specified extensions
def filelist( dir, recurs=True, *ext):
    """ recursive listing of files in a directory matching extension """
    result = []

    alist = [ os.path.abspath(os.path.join(dir,f)) for f in os.listdir( dir )]

    result.extend( [ f for f in filter( os.path.isfile, alist ) \
        if (not ext or (os.path.splitext(f)[1].lower() in ext)) ] )
    if recurs:
        for f in [ d for d in alist if not os.path.isfile(d)]:
            result.extend( filelist( f, True, *ext) )
    return result

# opensubtitle hash function
def hashFile(name):
    try:

        longlongformat = 'q'  # long long
        bytesize = struct.calcsize(longlongformat)

        f = open(name, "rb")

        filesize = os.path.getsize(name)
        hash = filesize

        if filesize < 65536 * 2:
                return "SizeError"

        for x in range(65536/bytesize):
                buffer = f.read(bytesize)
                (l_value,)= struct.unpack(longlongformat, buffer)
                hash += l_value
                hash = hash & 0xFFFFFFFFFFFFFFFF #to remain as 64bit number

        f.seek(max(0,filesize-65536),0)
        for x in range(65536/bytesize):
                buffer = f.read(bytesize)
                (l_value,)= struct.unpack(longlongformat, buffer)
                hash += l_value
                hash = hash & 0xFFFFFFFFFFFFFFFF

        f.close()
        returnedhash =  "%016x" % hash
        return returnedhash

    except(IOError):
            return "IOError"

# keeps only ascii alpha numeric character
def alphanum( string, fill=' ' ):
    string = to_ascii( string )
    return re.sub( '[^a-zA-Z0-9]{1,}', fill, string ).strip()

def to_ascii( string ):
    if not isinstance( string, unicode ):
        string = unicode(string,'cp850')
    return normalize( 'NFKD', string ).encode('ascii', 'ignore')

# boolean yes / no raw_input
def boolean_input(msg):
    res = None
    while res not in ['y','n']:
        res = raw_input( msg + ' (y/n):').lower()
    return( res=='y')

# ********** ARGUMENTS HANDLER ***********************************************
def parse_arguments():

    parser = argparse.ArgumentParser(description=ABOUT)

    parser.add_argument('-a','--alphabetical',
            action="store_true",default=False,
            help="sort by alphabetical order of title instead of rating")
    parser.add_argument('-r','--reverse',
            action="store_true", default=False,
            help="show media in reverse order")
    parser.add_argument('-d','--delete_cache',
            action="store_true", default=False,
            help="delete targeted files in cache. A confirmation is \
                    asked. To delete all cache use lm.py cache -d")
    parser.add_argument('-f','--filter',
            help="filter @keyword:filter1,filter2@keyword2:filter3, \
                    @genre:action@size:+500 will look at action movies \
                    bigger than 500Mb, @size:-100 will look at movies\
                    smaller than 100Mb, @unsure will filter files not\
                    found on opensubtitles with a bad match to imdb \
                    movies")
    parser.add_argument('-l','--long', action="store_true",
            help="Show long information on movie")
    parser.add_argument('-L','--very-long', action="store_true",
            help="Show full information on movie")
    parser.add_argument('-o','--outline', action="store_true",
            help="Show plot outline")
    parser.add_argument('--confirm', default=False,
            action="store_true",
            help="Manually confirm/search selected movies. May be usefull\
                    to ask for unsure movies only (ie with bad imdb match)\
                    with '-f @unsure' argument")
    parser.add_argument('--upload', default=False,
            action="store_true",
            help="Individually upload hash info to opensubtitles. Only\
                    files without opensubtitles correspondance will be\
                    selected")
    parser.add_argument('--download',
            help="Look for available subtitles for specific language.\
                    Use ISO639-1 codes, like eng/fre/dut/ger")
    parser.add_argument('-s', '--show-imdb', action="store_true",
            help="Show IMDb webpage of each movie in default navigator\
                    (don't use if you're listing a lot of files!)")
    parser.add_argument('-S', '--show', action="store_true",
            help="Show a sumup html page, with covers and usefull links")
    parser.add_argument( 'files', nargs="*",
            help="media files to check, by default looks at current dir")
    parser.add_argument('--reset', action="store_true",
            help="Delete all cache files (use it when corrupted")
    parser.add_argument('--debug', action="store_true",
            help="Display debug logging info, and write log message in\
                     ~/.lm/lm_log.txt")
    parser.add_argument('--version', action="store_true",
            help="Display current version")

    options = parser.parse_args()

    args = options.files

    if options.delete_cache +  options.confirm + \
            options.upload >1 :
        print("please choose ONE only from upload/confirm/delete")
        exit(2)

    if options.confirm or options.upload:
        options.long = True

    # take care of the 'unsure' filter
    if options.filter:
        options.filter = \
                options.filter.replace('unsure','unsure:')

    if options.show or options.show_imdb:
        import webbrowser
        global webbrowser

    if not args:
        if options.confirm:
            print("You have to explicitly give files when using --confirm")
            exit(2)
        args=['.']

    return( (options, args) )

# ********** Exceptions ******************************************************
class FilterParsingError(Exception):
    pass

class LoginError(Exception):
    pass

class OpensubtitlesError(Exception):
    pass


# fixed keys dictionary, to avoid error on small "key/value" data storage
class store(dict):

    def __init__(self,*args,**kwargs):

        self.static  = False
        self.update( *args, **kwargs )
        self.static  = True

    def __getitem__(self, key):
        if dict.__contains__(self,key):
            return dict.__getitem__(self,key)
        else:
            return None

    def __setitem__(self, key, val):
        if dict.__contains__(self,key) or not self.static:
            dict.__setitem__(self,key,val)
        else:
            raise KeyError, str(key) + " not in store keys"

    def update(self, *args, **kwargs):
        for k, v in dict( *args, **kwargs ).iteritems():
            self[k] = v


# ********** MAIN CLASS ******************************************************
class ListMovies():

    order_alpha     = False
    order_reverse   = False
    filter_phrase   = None

    disp_long       = False
    disp_very_long  = False
    disp_outline    = False

    def __init__( self, options=None ):

        if options:
            self.order_alpha = options.alphabetical
            self.order_reverse = options.reverse
            self.filter_phrase = options.filter
            self.disp_long = options.long
            self.disp_very_long = options.very_long
            self.disp_outline = options.outline

        self.log = logging.getLogger("LM")
        self.log.setLevel( logging.INFO )
        self.log.addHandler( NullHandler() )
        self.log.info( "LM initialization")

        # create hidden directory if needed at ~/.lm/
        cache_dir = os.path.expanduser('~/.lm')
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)

        self.cache_path_fn = os.path.join( cache_dir, 'cache_path')
        self.cache_hash_fn = os.path.join( cache_dir, 'cache_hash')

        # html output sumup file
        self.html_fn  = os.path.join( cache_dir, 'html_sumup.html')

        self.load_cache_path()
        self.load_cache_hash()

        self.i = imdb.IMDb()

        # opensubtitles XMLRPC server and tokern
        self.server = None
        self.token  = None

        # terminal coloration
        self.RED    = "\033[00;31m"
        self.YELLOW = "\033[00;33m"
        self.MAGEN  = "\033[01;35m"
        self.BLUE   = "\033[01;34m"
        self.END    = '\033[0m'

        # video files common extension
        # http://trac.opensubtitles.org/projects/opensubtitles/wiki/
        self.file_ext = [
                     '.3g2','.3gp','.3gp2','.3gpp','.60d','.ajp','.asf',
                     '.asx','.avchd','.avi','.bik','.bix','.box','.cam',
                     '.dat','.divx','.dmf','.dv','.dvr-ms','.evo','flc',
                     '.fli','.flic','.flv','.flx','.gvi','.gvp','.h264',
                     '.m1v','.m2p','.m2ts','.m2v','.m4e','.m4v','.mjp',
                     '.mjpeg','.mjpg','.mkv','.moov','.mov','.movhd',
                     '.movie','.movx','.mp4','.mpe','.mpeg','.mpg','.mpv',
                     '.mpv2','.mxf','.nsv','.nut','.ogg','.ogm','.omf',
                     '.ps','.qt','.ram','.rm','.rmvb','.swf','.ts','.vfw',
                     '.vid','.video','.viv','.vivo','.vob','.vro','.wm',
                     '.wmv','.wmx','.wrap','.wvx','.wx','.x264','.xvid']
        self.file_ext = [ unicode(ext) for ext in self.file_ext ]

        self.forbidden_words = ['divx','dvdrip','xvid','ts','dvdscr',
                     'cam','dvdscr','xvid','aac','r5']

        self.default_hash = {
            'bytesize'            : None,
            'imdb_check'          : 0,
            'm_id'                : None,
            'm_title'             : None,
            'm_canonical_title'   : None,
            'm_rating'            : None,
            'm_year'              : None,
            'm_genre'             : None,
            'm_countries'         : None,
            'm_director'          : None,
            'm_short_summary'     : None,
            'm_summary'           : None,
            'm_cast'              : None,
            'm_votes'             : None,
            'm_cover'             : None,
            'm_last_update'       : None,
            'o_imdb_id'           : None,
            'o_year'              : None,
            'o_check'             : 0,
            'o_title'             : None,
            'g_title'             : None,
            'g_year'              : None,
            'g_unsure'            : False
        }

        self.default_path = {
            'hash'          : None,
            'last_update'   : 0
            }

    # ********** CACHE HANDLERS **********************************************
    def load_cache_path(self):
        self.log.info("loading cache_path")
        try:
            with open(self.cache_path_fn,'r') as f:
                self.cache_path = cPickle.load(f)
            self.log.info("cache_path file loaded successfully")
        except:
            self.log.debug("cache_path not loaded ->  empty initilazation")
            self.cache_path = store()
            self.cache_path.static = False

    def _save_cache_path(self):
        self.log.info("saving cache_path")
        with open(self.cache_path_fn,'w') as f:
            cPickle.dump(self.cache_path,f)
        self.log.debug("cache_path saved")

    def load_cache_hash(self):
        self.log.info("loading cache_hash")
        try:
            with open(self.cache_hash_fn,'r') as f:
                self.cache_hash = cPickle.load(f)
            self.log.info("cache_hash file loaded successfully")
        except:
            self.log.debug("cache_hash not loaded ->  empty initilazation")
            self.cache_hash = store()
            self.cache_hash.static = False

    def _save_cache_hash(self):
        self.log.info("saving cache_hash")
        with open(self.cache_hash_fn,'w') as f:
            cPickle.dump(self.cache_hash,f)
        self.log.info("cache_hash saved")

    def _sync_cache(self):
    # delete self.cache_path items pointing whose hash isnt pointing
    # to an self.cache_hash key
        self.log.info("synchronizing caches")
        files = [ f for f, v in self.cache_path.iteritems() if \
                    not self.cache_hash.has_key(v['hash']) ]
        for f in files:
            del self.cache_path[f]

    def save_cache(self):
    # save cache function
    # save both at same time, after 'consistency' check:
    # every path from cache_path should point to an hash in cache_hash

        self.log.info("saving caches")
        self._sync_cache()
        self._save_cache_path()
        self._save_cache_hash()

    def delete_cache( self, files ):
    # delete a list of files in cache
    # -> obviously deleted in cache_path
    # -> but we delete also every hash (cache_hash)
    # not pointed by a file anymore

        cache_path = self.cache_path

        files = [ f for f in files if cache_path.has_key(f)]
        self.log.debug("%d entries to delete from cache_path" % len(files) )

        if len(files)>0:
            for f in files:
                print( os.path.basename(f) )
            print("*** trying to delete %i files from cache" % len(files))
            confirm = boolean_input('Please confirm cache deletion')

            if confirm:
                for f in files:
                    del cache_path[f]

                self.save_cache()

        else:
            print("no file to delete")

    def reset_cache_files(self):
        confirm = boolean_input("Confirm cache files deletion?")
        if confirm:
            if os.path.exists(self.cache_path_fn):
                os.remove(self.cache_path_fn)
            if os.path.exists(self.cache_hash_fn):
                os.remove(self.cache_hash_fn)
            if os.path.exists(self.html_fn):
                os.remove(self.html_fn)

    #
    def flush_out_str(self, out_str):
        sys.stdout.write( (out_str+'\r').encode('utf-8') )
        sys.stdout.flush()

    # ********** CACHE UPDATERS  *********************************************
    # When you update caches (cache_path, and cache_hash) order matters
    #
    # A/ first get files to consider
    # then run:
    #   1/ update_caches_with_paths
    #       this function will update cache_path and cache_hash keys
    #       and will set default keys/values
    #   2/ update_cache_hash_opensubtitles, to search for known hash
    #   3/ update_cache_hash_metadata, to complete metadata from imdb

    def update_caches_with_paths( self, abs_paths ):
    # Update cache_path with a list of new paths (abs_paths)
    # check if already in cache, and if cached version update
    # is more recent than last file modification.
    # i.e. if you modified you file after your last 'lm' call
    # 'lm' will re-hash your file
    # if hash error, None is stored in cache

        cache_path = self.cache_path
        cache_hash = self.cache_hash
        for path in abs_paths:

            if not( cache_path.has_key(path) and \
                    os.path.getmtime(path) < cache_path[path]['last_update']):

                self.log.info("adding new path to cache: %s" % path)
                cur_hash = hashFile(path)

                if cur_hash in ['SizeError','IOError']: cur_hash = None
                cache_path[path] = store( self.default_path )
                cache_path[path].update( {'hash':cur_hash,
                                   'last_update':time.time() } )

                # setting default keys.values in cache
                if cur_hash and not cache_hash.has_key(cur_hash):
                    self.log.debug("adding hash entry %s for file: %s" % ( \
                            str(cur_hash), path ) )

                    cache_hash[cur_hash] = store( self.default_hash )
                    cache_hash[cur_hash]['bytesize'] = os.path.getsize(path)

        self.save_cache()

    def update_cache_hash_opensubtitles(self):
    # Update cache_hash opensubtitles info
    # For movies which hash was not found in opensubtitles, will be tried
    # again only 6 hours after

        cache = self.cache_hash
        hashs = [ h for h in cache.keys() if
            not cache[h]['o_title'] and \
                 cache[h]['o_check'] < time.time()-3600*6 ]

        data = self.get_info_from_opensubtitles( hashs )

        for h in hashs:

            now = time.time()
            cache[h]['o_check'] = now

            if data.has_key(h):
                info = data[h]
                if info:
                    try:
                        open_info = {'o_imdb_id':info['MovieImdbID'],
                                       'o_title':info['MovieName'],
                                        'o_year':info['MovieYear']}
                        cache[h].update( open_info )

                    except:
                        self.log.debug("faild to update (%s) open info" +\
                                " with open answer %s " % (str(h),str(info)) )
                        pass

        if len(hashs)>0:
            self.save_cache()

    # *********** OPENSUBTITLES CONNECTIONS **********************************
    def status_ok(self, ans):
        status = False
        try:
            if ans.has_key("status") and ans["status"] == "200 OK":
                self.log.debug("OpenSubtitles answer status OK")
                status = True
            else:
                self.log.warning("OpenSubtitles answer status DOWN")

        except Exception, e:
            self.log.error(str(e))

        finally:
            return( status )

    def login(self, user="", password=""):
        try:
            server = xmlrpclib.ServerProxy(OPENSUBTITLE_DOMAIN)
            log    = server.LogIn(user,password,'en',OPENSUBTITLE_USER_AGENT)

            if self.status_ok(log):
                self.log.debug("OpenSubtitles login OK")
                self.server = server
                self.token  = log['token']
            else:
                raise LoginError

        except LoginError, e:
            self.log.warning("OpenSubtitles login DOWN, %s" % str(e) )
            #raise LoginError

        except Exception, e:
           self.log.error("OpenSubtitles login process DOWN, %s" % str(e))


    def logout(self):
        if self.token:
            try:
                self.server.LogOut(self.token)
                self.log.debug("OpenSubtitles logout OK")
            except Exception, e:
                self.log.warning("OpenSubtitles logout DOWN, %s" % str(e))

    # retrive general info for a list of movie hash
    def get_info_from_opensubtitles( self, hashs ):
            data = {}

            if len(hashs)>0:
                self.log.info("request OpenSubtitle info for %d hashes" %\
                        len(hashs))
                try:
                    self.login()
                    for k in range( len(hashs)/150+1 ):
                        res = self.server.CheckMovieHash( self.token,
                                hashs[150*k:(150*(k+1))] )
                        data.update( res['data'] )
                    self.logout()
                except:
                    print("Error when retrieving hash from opensubtitles")
                    pass

                for k, v in data.iteritems():
                    if len(v)==0: data[k]=None

            return(data)

    def path_from_hash(self, cur_hash):
    # Returns the lastest modified file in cache_path pointing to this hash
    # a path points to 1 hash only
    # an hash can be pointed by unlimited path
    # [cache_path] * ----> 1 [cache_hash]
    # return a dictionary, 'path', 'cache_time', 'file_time'

        path = [ (k,v['last_update']) for k,v in self.cache_path.iteritems() \
                if v['hash'] == cur_hash and os.path.exists(k) ]

        if len(path)>0:
            update_time = [ k[1] for k in path ]
            max_update_time = max(update_time)
            path = path[ update_time.index( max_update_time ) ][0]
            res = {'path':path, 'cache_time':max_update_time,
                        'file_time':os.path.getmtime(path)}
        else:
            res = None
        return(res)


    def update_cache_hash_metadata(self):
    # Update metadata from IMDB for
    # If movie hash found in opensubtitles:
    # we already know the imdb id -> simple call
    # Else:
    # we use hand design algorithm based on filename to detect imdb id.
    # 1/ guess the title with filename
    # 2/ call imdb with this query
    # 3/ look for the best local title match
    #
    # If movie hash not found in opensubtitle and file modified after
    # our last imdb call -> we call imdb again

        cache = self.cache_hash
        hashs = []
        for h,v in cache.iteritems():

            p_info = self.path_from_hash(h)
            if p_info:
                path, c_time = p_info['path'], p_info['cache_time']
                updt_after   = not v['o_title'] and v['m_last_update']<c_time
                path_exists  = os.path.exists(path)

                if path_exists and (not v['m_last_update'] or updt_after):
                    hashs.append(h)

        idx, last_len, total = 1, 0, len(hashs)

        for h in hashs:
            self.log.info("get metadata for hash: %s" % str(h) )
            out_str = u"Getting metadata: [%(index)i/%(nb_movies)i] "
            out_str = out_str % {'index':idx,'nb_movies':total}
            if len(out_str) < last_len:
                sys.stdout.write(' '*last_len+'\r')
            self.flush_out_str(out_str)

            self.__get_metadata(h)
            cache[h]['imdb_check'] = time.time()

            if idx % 10 == 0:
                self.save_cache()
            idx += 1

        if len(hashs)>0:
            self.save_cache()
            self.flush_out_str(' '*last_len+'\r')


    def __get_metadata(self, cur_hash):
    # "Get metadata for files not already in cache
    # @param files: list of filenames (path or basenames)

        cache_hash = self.cache_hash
        imdb_id    = None

        try:

            # if we have an imdb_id from opensubtitles for this hash
            imdb_id = cache_hash[cur_hash]['o_imdb_id']

            if imdb_id:
                self.log.info("IMDb id stored from Opensubtites %s" % imdb_id)
                result = self.i.get_movie(imdb_id)
                if result:
                    self.__fill_metadata( cur_hash, result )
                else:
                    self.log.warning("failed to get movie info from IMDB")

            else:
                # we need to guess a title, from a file pointing to this hash
                self.log.info("no IMDb id stored from OpenSubtitles")

                path  = self.path_from_hash( cur_hash )['path']
                guess = self.guessed_title_year( path )
                self.log.debug("info guessed from filaneme %s" % str(guess) )

                cache_hash[cur_hash].update( guess )

                results = self.i.search_movie( guess['g_title'] )

                if results:
                    self.log.info("finding best match in answers")
                    best_result, unsure = self.best_match( guess['g_title'],
                            guess['g_year'], results)

                    self.log.debug("best result for %s: %s" % \
                            (guess['g_title'], best_result.get('title')))

                    cache_hash[cur_hash]['g_unsure'] = unsure
                    self.i.update(best_result)
                    self.__fill_metadata( cur_hash, best_result)
                else:
                    self.log.info("no result from IMDb, empty metadata")
                    self.__fill_metadata( cur_hash, None )
                    cache_hash[cur_hash]['g_unsure'] = True

        except imdb.IMDbError, e:
            print( "Connection error, current movie: [%s]" % \
                    imdb_id if imdb_id else guess['g_title'] )
            print e
            self.save_cache()
            sys.exit(2)


    # ********** UNKNOW HASH MATCHER *****************************************
    def best_match(self, guess_title, guess_year, results=None):
        # Check match between the found movie and original filename

        if not results:
            results = self.i.search_movie( guess_title )

        _guessed_title = alphanum( guess_title ).lower()
        _guessed_year  = guess_year

        _results = [ r for r in results if isinstance(r,imdb.Movie.Movie) ]
        if _guessed_year:
            _results = [ r for r in _results if r.has_key('year') \
                                        and r['year'] == _guessed_year ]

        _best_ratio  = 0
        _best_result = None

        for r in _results:

            _list_titles  = [ alphanum(title.split('::')[0]).lower() \
                                    for title in (r.get('akas') or [])]
            _list_titles += [ alphanum(r.get('title')).lower() ]

            for other_title in _list_titles:
                cur_ratio = SequenceMatcher(None,
                            other_title,_guessed_title).ratio()

                if cur_ratio > _best_ratio:
                    _best_ratio, _best_result = cur_ratio, r
                    self.log.info("ratio ==> %s (for [%s]) %f" % \
                                    ( other_title, _guessed_title, cur_ratio))

        unsure = _best_ratio < 0.7

        if _best_ratio < 0.7 and _guessed_year:
            self.log.info( "ratio <0.7 & year, we retry on base results")
            _best_result, unsure = self.best_match(guess_title,None,results)

        return _best_result, unsure

    def guessed_title_year( self, files ):
    # Try to guess title from movie filename
    # @param files: filename to parse

        # we take everything before information in bracket
        # or square bracket, as these info are usually not part of the title
        title_reg = re.compile('^[^[(]+')
        # the year is most of time placed between
        # the title and other information, we are intersted by what is before
        before_year_reg = re.compile(r'(.*)[12][1089][0-9]{2}.*')
        # in some case, we have the title with lowercases,
        # and other info (e.g. language) fully uppercase, this regex test this
        upper_reg = re.compile(r'(^.+?)[A-Z]{2}.*')

        init_title = os.path.splitext(os.path.basename(files))[0]

        tmp_title = alphanum(
                (re.findall(title_reg,init_title) or [init_title])[0] )
        # 2nd regex
        tmp_title = re.sub(before_year_reg, r'\1', tmp_title) or tmp_title
        # 3rd regex
        title     = re.sub(upper_reg,r'\1', tmp_title) or tmp_title

        # In some cases, the previous regex give a wrong title,
        # we try to detect this by cancelling too short title
        if len(title) < 3:
            title = tmp_title

        title = title.strip().lower()

        #we now remove forbidden words
        title_words = title.split(' ')
        for forbidden in self.forbidden_words:
                if forbidden in title_words:
                    title_words.remove(forbidden)
        title = ' '.join(title_words)
        guessed_year = re.findall('([12][1089][0-9]{2})', init_title) or None
        guessed_year = int(guessed_year[0]) if guessed_year else None
        if guessed_year < 1800 or 2100 < guessed_year:
            guessed_year = None

        return {'g_title':title.strip(), 'g_year':guessed_year}



    def __fill_metadata(self, cur_hash, found):
    # Fill metadata for one movie
    # @param cur_hash: current hash to update
    # @param found: the imdb movie object selected

        current = self.cache_hash[cur_hash]

        current['m_last_update'] = time.time()

        if found:
            current['m_id']    = found.movieID
            current['m_title'] = found.get('title')
            current['m_canonical_title']=found.get('smart canonical title')
            current['m_rating'] = found.get('rating')
            current['m_year']   = found.get('year')
            current['m_genre']  = found.get('genre') or []
            current['m_countries'] = found.get('countries') or []
            current['m_director'] = [director.get('name') for director in
                    (found.get('director') or [])]
            current['m_short_summary'] = found.get('plot outline')
            current['m_summary'] = (found.get('plot') or [''])[0]
            current['m_cast'] = [ actor.get('name') for actor in
                    (found.get('cast') or [])]
            current['m_votes'] = found.get('votes')
            current['m_cover'] = found.get('cover url') or []

        else:
            current.update({
                    'm_id':'000000', 'm_title':'___NOTFOUND___',
                    'm_canonical_title':'___NOTFOUND___',
                    'm_genre':[],'m_countries':[],
                    'm_director':[], 'm_cast':[], 'm_cover':[],
                    'm_votes':0, 'm_summary':'.'*20,'m_rating':0,
                    'm_year':1900,'m_short_summary':'.'*20})


    # ********** MANUAL CONFIRMATION *****************************************
    def manual_confirm( self, files ):
        """ @param files: list of files to be confirmed by hand """

        update_count = 0
        for f in files:
            out_str =  "\n***************\n"
            out_str += "File to confirm\n"
            out_str += "***************\n"
            out_str += "absolute path : %s\n"
            out_str += "basename      : %s\n"
            out_str = out_str % ( f, os.path.basename(f) )
            print( out_str )

            update_count += self.__manual_confirm( f )
            print("\n%i movies updated" % update_count )


    def __manual_confirm( self, f, ask=False ):
    # Go through interaction with user to confirm a file with
    # either an IMDB ID or a title or year
    # @param f: an absolute path
    # @param ask: boolean, do you let the chance to exit the process?

        if ask:
            if not boolean_input('Try again for this movie?'):
                return(False)

        cur_hash = self.cache_path[f]['hash']

        try:

            if self.cache_hash[cur_hash]['m_id'] != '000000':
                self.pretty_print(f)
                confirm = boolean_input("Do you confirm stored info?")
                if confirm:
                    self.cache_hash[cur_hash]['g_unsure']=False
                    return( True )

            input_id = boolean_input("Will you provide an IMDb id?")
            if input_id:
                imdb_id =raw_input('please enter the IMDb id for this movie:')
                result = self.i.get_movie(imdb_id)
            else:
                title =raw_input('please enter movie title:')
                year  =raw_input('please enter year, leave blank if unknown:')
                if year=='':
                    year = None
                result, unsure = self.best_match( title, year )

            if result:
                print( '--> movie found title: %s' % result['title'] )
                print( '--> movie found  year: %s' % result['year'] )
                agree = boolean_input('Confirm this result?')
                if agree:
                    self.__fill_metadata(cur_hash, result)
                    self.cache_hash[cur_hash].update(\
                        { 'g_title':result['title'],
                          'g_year':result['year'], 'g_unsure':False })
                    self.save_cache()
                    print("movie saved")
                    return( True )
                else:
                    return( self.__manual_confirm( f, ask=True ) )
            else:
                print( '--> nothing found!')
                return( self.__manual_confirm( f, ask=True ) )

        except imdb.IMDbError, e:
            print( "Connexion error")
            print e
            return( self.__manual_confirm( f, ask=True ) )

    # ********** UPLOAD HASH TO OPENSUBTITLES ********************************
    def upload_to_opensubtitles(self, files):
    # filter a list of files to get only those which hash was not
    # found in opensubtitles, and will ask the user if he wants to
    # send the couple (imdb_id, hash) to opensubtitles.
    # @param files: a list of absolute path

        files = [ f for f in files if \
                    not self.cache_hash[
                        self.cache_path[f]['hash']]['o_imdb_id']]
        if len(files)>0:

            to_upload = []
            for f in files:

                cur_hash = self.cache_path[f]['hash']
                imdb_id  = self.cache_hash[cur_hash]['m_id']
                bytesize = str(self.cache_hash[cur_hash]['bytesize'])

                self.pretty_print(f)
                msg = "Do you want to send hash info to opensubtitles?"
                insert = boolean_input(msg)
                if insert:
                    to_upload.append( { 'moviehash':cur_hash,
                                    'moviebytesize':bytesize,
                                           'imdbid':imdb_id } )

            if len(to_upload)>0:
                try:
                    self.login()
                    call = self.server.InsertMovieHash( self.token, to_upload)
                    print( call )
                    logout = self.logout()

                    for v in to_upload:
                        h = v['moviehash']
                        self.cache_hash[h]['o_check'] = None

                    self.save_cache()

                except Exception, e:
                    print("!!! Error when uploading hash to opensubtitles")
                    print( e )
                    if self.token:
                        logout = self.logout()
                        print( 'LOGOUT ***', logout )

    # ********** DOWNLOAD SUBTITLES FROM OPENSUBTITLES ***********************

    def download_subtitle(self, files, language):

        ref, query = self.download_subtitles_query( files, language )
        self.log.info("download subtitles query info %s" % str(query))

        if len(query)==0:
            self.log.info("all subtitles already downloaded!")
            return

        self.login()
        sub_refs = self.server.SearchSubtitles( self.token, query )

        if self.status_ok(sub_refs):
            if sub_refs['data'] != False:

                sub_ids = self.download_subtitles_filter(ref,sub_refs['data'])

                self.log.debug( "list of subtitlesid to donwload: %s" %\
                        ", ".join( sub_ids ) )

                subs     = self.download_subtitleids( sub_ids )
                if subs:
                    self.download_subtitles_write(ref,subs,language)

            else:
                self.log.info( "no subtitles found on OpenSubtitles %s" %\
                        str(sub_refs) )

        else:
            self.log.error("Subtitles download failed: %s" % str(sub_refs) )
#            raise OpensubtitlesError

        self.logout()

    def download_subtitles_query( self, files, lang ):
    # build a useful info dictionary and the list of queries
    # to be passed as argument to SearchSubtitles XMLRPC call

        # defining query to send
        ref, query = {}, []
        for f in files:

            # check if we already downloaded subtitles for this movie
            pattern = lang.upper() + "_LM[\d]{1,}\.srt$"
            filedir = os.path.dirname(f).decode(sys.getdefaultencoding())
            old_subs = [ old for old in filelist(filedir,False) \
                    if re.search(pattern, old) ]

            h           = self.cache_path[f]['hash']
            osbtls      = self.cache_hash[h]['o_imdb_id'] != None
            imdb_id     = self.cache_hash[h]['m_id']
            byte_size   = self.cache_hash[h]['bytesize']
            fn          = os.path.basename(f)

            if imdb_id and len(old_subs)==0:
                ref[f] = {'osbtls':osbtls, 'imdb_id':imdb_id,
                          'file':fn, 'hash':h }
                if osbtls:
                    query.append({ 'sublanguageid':lang,
                                       'moviehash':str(h),
                                   'moviebytesize':str(byte_size)})

                # even if hash is found in opensubtitles, we add
                # another query with imdb_id
                query.append({'sublanguageid':lang,'imdbid':imdb_id})

        return( (ref, query) )

    def download_subtitles_filter(self, ref, subs):
    # filters subs (list result of SearchSubtitles call)
    # and associates to each ref key, bests found subtitles (hash match)
    # or most downloaded subtitles
    # @param ref: output[0] of download_subtitles_query
    # @param subs: result['data'] of a SearchSubtitles XMLRPC call

        for k, v in ref.iteritems():

            keep = [ s for s in subs if s['MovieHash']==v['hash'] ]
            if len(keep)==0:
                keep = [ s for s in subs if s['IDMovieImdb']==
                        str(int(v['imdb_id'])) ]

            if len(keep)>0:
                keep.sort( key=lambda k: k['SubDownloadsCnt'],
                            reverse = True )

                v['keep'] = [ k['IDSubtitleFile'] for k in keep[0:3]]

            else:
                v['keep'] = None


        sub_ids = set([])
        for r, v in ref.iteritems():
            if v['keep']:
                sub_ids.update( v['keep'] )

        return(list(sub_ids))


    def download_subtitleids(self,sub_ids):
    # download, decode, and decompress a list of subtitles
    # @param sub_ids; list of subtitles id
        subs = None

        try:
            result = self.server.DownloadSubtitles(self.token,sub_ids)
        except Exception, e:
            self.log.error("OpenSubtitle download sub error" % str(e) )
            return( None )

        if self.status_ok(result):
            if result['data'] != 'False':
                subs = {}
                for sub in result['data']:
                    sub_d = base64.standard_b64decode(sub['data'])
                    sub_d = zlib.decompress( sub_d, 47 )
                    subs[sub['idsubtitlefile']] = sub_d

        return(subs)

    def download_subtitles_write(self,ref,subs,lang):
    # Write downloaded subtitles in movies directories with suffixe:
    # _LANG_LM[\d].srt
    # @param red: output of download_subititles_query
    # @param subs: list of decompressed subs [{'IDSubtitleFile':,'Data'}]

        for k, v in ref.iteritems():
            keep = v['keep']
            if keep:
                for i in range(len(keep)):
                    sub_file = os.path.splitext(k)[0] + '_' + lang.upper() + \
                            '_LM' + str(i+1) + '.srt'
                    f = codecs.open(sub_file,'wb')
                    f.write(subs[keep[i]])
                    f.close()

    # ********** GATHERING & FILTERING FILES *********************************
    def get_files(self,args):
    # Return files from args, if isdir -> recursive search
        result = []
        self.log.info("interpreting file/dir argument")

        if args[0]=='cache':
            self.log.info("loading all cache entries")
            result.extend( self.cache_path.keys() )
        else:
            for arg in args:
                if not arg:
                    continue        #we don't want empty arg
                encoding = locale.getdefaultlocale()[1]
                if encoding: arg = arg.decode( encoding )

                real_path = os.path.expanduser(arg)

                if arg == real_path and not os.path.exists(arg):
                    real_path = os.path.join( os.getcwd(), real_path )

                if os.path.isdir(real_path):
                    self.log.debug("dir to parse: %s" % real_path )
                    self.log.debug("dir var type: %s" % type(real_path) )

                    result.extend( filelist(
                        real_path, True, *self.file_ext ) )
                elif os.path.isfile(real_path):
                    result.append(arg)

        return result

    def user_filter(self, files):
    # Filter movies according to user given arguments
        self.log.info("number of files before filtering: %d" % len(files))
        filt = self.filter_phrase
        try:
            while filt:

                if filt[0]!='@':
                    raise FilterParsingError
                end = filt.find(':')

                if end == -1:
                    raise FilterParsingError
                filter_type = filt[1:end]

                if not filter_type in ['genre','director','actor','size',
                       'country','unsure']:
                    raise FilterParsingError

                if filter_type=="actor":
                    filter_type='cast'
                elif filter_type=="country":
                    filter_type="countries"
                filt = filt[end+1:]
                end = filt.find('@')

                if end == -1:
                    end = None
                keys = set([key.lower() for key in filt[:end].split(',')])
                filt = filt[end:] if end else ''

                if filter_type =='size':
                    self.log.info("filtering by size")

                    if (len(keys)>1):
                        raise FilterParsingError
                    try:
                        keys = list(keys)[0]

                        if keys[0] in ['-','+']:
                            sign = 1 if keys[0] == '+' else -1
                            keys = keys[1:]
                        else:
                            sign = 1

                        keys = float(keys)
                        self.log.info("filtering key: %s%f" % \
                                ( "<" if sign==1 else ">", keys))
                    except:
                        raise FilterParsingError
                    files = [ f for f in files if \
                            sign*keys < sign*os.path.getsize(f)/(1020*1024) ]


                elif filter_type == 'unsure':
                    self.log.info("filtering unsure movies")
                    files = [ f for f in files if \
                        self.cache_hash[\
                            self.cache_path[f]['hash']]['g_unsure'] ]

                else:
                    self.log.info("filtering type: %s" %filter_type )
                    self.log.info("filtering keys: %s" % ", ".join(keys))

                    filter_type = 'm_' + filter_type
                    files = filter( lambda m:\
                        set([key.lower() for
                        key in self.hash_from_path(m)[filter_type]]).\
                                intersection(keys), files)
        except FilterParsingError:
            self.log.error("Invalid filter ! Please read README for syntax")
            files = []

        finally:
            self.log.info("number of files after filtering %d" % len(files))
            return files

    def filter_and_sort_files( self, files):
    # filter the list of files,
    # according to video extensions provided, and user filters

        if self.filter_phrase:
            files = self.user_filter(files)

        if self.order_alpha:
            keyword = 'm_canonical_title'
        else:
            keyword = 'm_rating'

        files.sort( key=lambda f: self.hash_from_path(f)[keyword],\
                reverse=self.order_reverse)

        return(files)

    def hash_from_path(self,path):
        try:
            cur_hash    = self.cache_path[path]['hash']
            result      = self.cache_hash[cur_hash]
        except:
            self.log.error("this path doesnt belong to cash_path %s" % path )
            result      = store()

        return( result )

    # ********** DISPLAYERS **************************************************
    def show_list(self, files):
        for f in files:
            self.pretty_print(f)


    def pretty_print(self, filename):
    # Print movie with metadata and colors according to arguments

        h = self.hash_from_path(filename)
        if not h['m_id']:
            return(0)

        values_dict = {'b':self.BLUE,
                       'e':self.END,
                       'header':self.RED + '/!\\ ' + self.END if \
                               h['g_unsure'] else '',
                       'title':(self.MAGEN if h['o_imdb_id'] \
                               else self.YELLOW)+to_ascii(h['m_title'])+\
                               self.END,
                       'rating':str(h['m_rating']),
                       'year':h['m_year'],
                       'genre':"%s" % ', '.join(h['m_genre']),
                       'filename':os.path.basename(filename),
                       'director':', '.join(h['m_director']),
                       'size': str(int(h['bytesize'] / (1024*1024))) \
                               if h['bytesize'] else None
                      }

        if self.disp_very_long:
            out_str  =u"%(header)s%(title)s (%(b)srating%(e)s: %(rating)s)\n%"
            out_str +="(b)syear%(e)s: %(year)s %(b)sgenre%(e)s: %(genre)s\n%"
            out_str +="(b)sfile%(e)s: %(filename)s %(b)ssize%(e)s: %(size)sMo"
            out_str +="\n%(b)sdirector%(e)s: %(director)s\n"
            out_str = out_str % values_dict

            cast_header = self.BLUE+u"cast"+self.END+": "
            len_cast_header = len(cast_header) - len(self.BLUE) - len(self.END)
            out_str+=cast_header
            first = True
            for actor in h['m_cast']:
                if first:
                    first = False
                    out_str += actor+'\n'
                else:
                    out_str+=len_cast_header*u' '+actor+'\n'
            out_str += "\n" + self.BLUE + "summary"+self.END+": %s\n---\n" % \
                    h['m_summary']
        elif self.disp_long:
            out_str = u"%(header)s%(title)s (%(year)s,%(rating)s,%(size)sMo) "
            out_str += "[%(b)s%(genre)s%(e)s] from %(director)s: "
            out_str += "%(filename)s\n"
            out_str = out_str % values_dict
        else:
            out_str = u"%(header)s%(title)s (%(filename)s)\n" % values_dict
        sys.stdout.write(out_str.encode('utf-8'))
        if self.disp_outline and h['m_short_summary']:
            sys.stdout.write(unicode( \
                    '*** ' + h['m_short_summary']+'\n').encode('utf-8'))

    def html_print(self, files):
    # Show the list of files, using metadata according to arguments

        cell = u"<td width=200 height=250><a href=\"%(imdb)s\">\
           %(title)s</a><br> \
           <font color=%(color)s>%(genre)s<br>\
           note: %(rating)s, votes: %(votes)s<br>\
           size: %(size)iMo</font><br>\
           <a href='%(trailer)s'><img src='%(cover)s' height=150></a><br>\
           <small>%(file)s</small></td>\n"

        with codecs.open(self.html_fn,'w','utf-8') as out_file:
            out_file.write("<table>\n")
            count = 0
            for f in files:
                if count % 5 == 0:
                    if count > 0: out_file.write("</tr>")
                    out_file.write("<tr height=200>")

                h = self.hash_from_path(f)
                if h['m_id']:
                    values_dict = {
                        'imdb' :'http://www.imdb.com/title/tt'+h['m_id'],
                        'file' : os.path.basename(f)[0:20],
                        'size' : round(h['bytesize']/(1024*1024),1)\
                        if os.path.exists(f) else 0,
                        'title': h['m_title'],
                        'color': '#FF3333' if h['g_unsure'] else '#808080',
                        'rating' : str(h['m_rating']) or 'None',
                        'votes': str(round(h['m_votes']/1000,1))+'K' if \
                                h['m_votes'] else 'None',
                        'cover': h['m_cover'],
                        'genre': ', '.join(h['m_genre'][0:2]),
                     'trailer':'http://www.youtube.com/results?search_query='+
                                alphanum( h['m_title'],'+')+'+trailer'
                                }
                    # print values_dict
                    finalcell = cell % values_dict
                    out_file.write( finalcell )
                count += 1
            out_file.write("</tr></table>")
        webbrowser.open_new_tab( "file://%s" % self.html_fn )

    def imdb_show(self, files):
        for f in files:
            h = self.hash_from_path(f)
            if h['m_id']:
                webbrowser.open_new_tab(imdb.imdbURL_movie_main % h['m_id'])

if __name__ == "__main__":

    options, args  = parse_arguments()

    if options.debug:
        consoleLogging( LOG_FORMAT, logging.DEBUG )

        rootdir = os.path.expanduser(u"~/.lm")
        filelog = os.path.join( rootdir, u"lm_log.txt" )
        if not os.path.exists( rootdir ):
            os.mkdir( rootdir )
        fileLogging( LOG_FORMAT, logging.DEBUG, filelog )

        logger.info("argparse namespace: %s" % str(options) )
        logger.info("arg files type: %s" % \
                ', '.join([str(type(f)) for f in args]) )
        logger.info("file system encoding: %s" % sys.getfilesystemencoding())
        logger.info("system encoding: %s" % sys.getdefaultencoding())
        logger.info("locale encoding: %s" % locale.getdefaultlocale()[1])

    else:
        consoleLogging( LOG_FORMAT, logging.ERROR )

    LM  = ListMovies(options)

    if options.version:
        print( VERSION )
        sys.exit()

    if options.reset:
        LM.reset_cache_files()
        sys.exit()

    files = LM.get_files(args)

    if options.delete_cache:
        LM.delete_cache(files)
        sys.exit()

    LM.update_caches_with_paths( files )
    LM.update_cache_hash_opensubtitles()
    LM.update_cache_hash_metadata()
    files = LM.filter_and_sort_files(files)

    if options.confirm:
        LM.manual_confirm(files)

    elif options.upload:
        LM.upload_to_opensubtitles(files)

    elif options.download:
        LM.download_subtitle(files, options.download)

    elif options.show:
        LM.html_print(files)

    elif options.show_imdb:
        LM.imdb_show(files)

    else:
        LM.show_list( files )

