from wordpress_xmlrpc import Client, WordPressPost
from wordpress_xmlrpc.methods.posts import GetPosts, NewPost, EditPost, GetPost
from wordpress_xmlrpc.methods.taxonomies import *
from wordpress_xmlrpc.exceptions import InvalidCredentialsError,ServerConnectionError
import logging
import os
from multiprocessing.dummy import Pool as ThreadPool
from configobj import ConfigObj
import requests
import colorama
from colorama import Fore, Back, Style
colorama.init(convert=True)
import socket
import shutil
import http.client
import xmlrpc.client
import datetime

class ProxiedTransport(xmlrpc.client.Transport):
    #def set_timeout(self, timeout):
    #    self.timeout = timeout

    def set_proxy(self, host, port=None, headers=None):
        self.proxy = host, port
        self.proxy_headers = headers

    def make_connection(self, host):
        #if self.timeout:
        #    connection = http.client.HTTPConnection(*self.proxy)
        #else:
        connection = http.client.HTTPConnection(*self.proxy)

        connection.set_tunnel(host, headers=self.proxy_headers)
        self._connection = host, connection
        return connection


class XmlrpcPoster():
    def __init__(self):
        self.logger = logging.getLogger('xmlrpc_poster')

        try:
            self.config = ConfigObj('config.ini')
        except:
            self.logger.exception('load config')
            return

        self.proxy = self.config.get('proxy')
        if self.proxy != 'None':
            self.transport = ProxiedTransport()
            proxy, port = self.proxy.split(':')
            self.transport.set_proxy(proxy, port)


        socket.setdefaulttimeout(int(self.config.get('timeout')))
        self.convert_url = bool(self.config.get('convert_post_url'))
        self.convert_post_url_timeout = int(self.config.get('convert_post_url_timeout'))
        self.white_foledrs_name = self.config.get('white_foledrs_name')
        #self.file_path_urls = os.path.join(os.getcwd(),self.config.get('file_name_urls'))
        self.file_name_urls = self.config.get('file_name_urls')
        self.file_path_posts_folder = os.path.join(os.getcwd(),self.config.get('file_name_posts_folder'))
        self.thread_count = int(self.config.get('thread_count'))


    def load_urls_list(self,file_name):
        try:
            with open(file_name, 'r') as file:
                urls = [line.rstrip() for line in file]
            return urls
        except:
            self.logger.exception('load_urls_list')

    def load_posts_list(self,dir_name):
        try:
            posts = []
            file_names = [x for x in os.listdir(dir_name) if x.endswith(".txt")]

            for file_name in file_names:
                if file_name == self.file_name_urls:
                    continue
                #with open(os.path.join(dir_name,file_name), 'r',encoding='UTF-8') as file:
                with open(os.path.join(dir_name, file_name), 'r', encoding='UTF-8') as file:
                    post = [line.rstrip() for line in file]
                    if post:
                        posts.append(post)

            return posts
        except:
            self.logger.exception('load_urls_list')

    def get_category(self,wp,terms):
        # получаем категорию, если такой нет то создаем
        try:
            find_terms = []
            exist_terms = wp.call(GetTerms('category',{'search':terms}))
            if len(exist_terms) > 1:
                for exist_term in exist_terms:
                    name = str(exist_term)
                    if name.lower() == terms.lower():
                        find_terms.append(exist_term)
                        break
            else:
                find_terms = exist_terms

            if not exist_terms:
                tag = WordPressTerm()
                tag.taxonomy = 'category'
                tag.name = terms
                tag.id = wp.call(NewTerm(tag))
                find_terms = wp.call(GetTerms('category', {'search': terms}))

            return find_terms
        except (InvalidCredentialsError, ServerConnectionError):
            return None
        except:
            self.logger.exception('get_category')


    def send_post_map(self, data):
        nom = data.get('nom')
        url = data.get('url')
        post_text = data.get('post')
        # новые поля
        title = data.get('title')
        date_time = data.get('date')
        category = data.get('category')
        # для тестов
        #date_time = datetime.datetime(2020, 6, 22)
        #category = 'test categoryes'

        url, user, password = url.split(';')
        try:
            if self.proxy != 'None':
                wp = Client(url + '/xmlrpc.php', user, password,transport=self.transport)
            else:
                wp = Client(url+'/xmlrpc.php', user,password)
        except:
            #self.logger.exception('Client')
            self.logger.info(f'{nom}:{url} - {Fore.RED}failed{Style.RESET_ALL}')
            return {'url':url,'post_id':False}
        try:

            post = WordPressPost()
            post.mime_type = "text/html"
            if title:
                post.title = title
            else:
                post.title = ''
            post.content = post_text

            if date_time:
                post.date = datetime.datetime.strptime(date_time,'%d.%m.%Y %H:%M')
            if category:
                # добавляем категорию
                categories = self.get_category(wp, category)
                if categories:
                    post.terms = categories
                else:
                    self.logger.info(f'{category} dont created')
            post.post_status = 'publish'
            try:
                post.id= wp.call(NewPost(post))
            except (InvalidCredentialsError, ServerConnectionError, socket.timeout):
                self.logger.info(f'{nom}:{url} - {Fore.RED}failed{Style.RESET_ALL}')
                return {'url': url, 'post_id': False}

            # пока не решил брать отсюда урл или нет
            #post_new = wp.call(GetPost(post.id))
            self.logger.info(f'{nom}:{url} send post! {Fore.GREEN}Post urls {url}/?p={post.id}{Style.RESET_ALL}')
            return {'url': url, 'post_id': post.id}

        except:
            self.logger.exception('send_post')
            return {'url':None,'post_id':None}

    def create_project_log(self,project):
        path = os.path.join(self.file_path_posts_folder, project)
        page_folders_name = [x for x in os.listdir(path) if os.path.isdir(os.path.join(path,x))]
        repotrs= []
        for page in page_folders_name:
            repotrs.append(os.path.join(self.file_path_posts_folder, project,page,'report.csv'))

        with open(os.path.join(self.file_path_posts_folder, project,'report.csv'), 'wb') as wfd:
            for f in repotrs:
                with open(f, 'rb') as fd:
                    shutil.copyfileobj(fd, wfd)

    def create_log(self,result,project,page):
        with open(os.path.join(self.file_path_posts_folder,project,page,'report.csv'),'w') as file:
            #file.writelines('post url;status\n')
            for r in result:
                if r['post_id']:
                    if self.convert_url:
                        try:
                            res = requests.head(f"{r['url']}/?p={r['post_id']}", timeout=self.convert_post_url_timeout)
                            res_str = f"{res.next.url};OK"
                            pass
                        except:
                            res_str = f"{r['url']}/?p={r['post_id']};OK (url not defined)"
                    else:
                        res_str = f"{r['url']}/?p={r['post_id']};OK"
                else:
                    res_str = f"{r['url']}/?p={r['post_id']};FAIL"
                file.writelines(res_str + '\n')

    def get_post_title_data_category(self,post):
        # возвращаем информацию из поста
        try:
            date = None
            category = None
            post_text = ''
            if len(post) > 1:
                for p in post:
                    f = p.find(':')
                    if p[:f] == 'data':
                        # это дата
                        date = p[f+1:]
                    elif p[:f] == 'category':
                        # это категория
                        category = p[f+1:]
                    else:
                        post_text = post_text + p
            else:
                post_text = post.pop()

            h1_st = post_text.find('<h1>')
            h1_en = post_text.find('</h1>')
            title = post_text[h1_st + 4:h1_en]

            return title,post_text,date,category
        except:
            self.logger.exception('get_post_title_data_category')

    def get_page_folders(self,project_folder,page_folder_name):
        urls = self.load_urls_list(os.path.join(self.file_path_posts_folder, project_folder,page_folder_name, self.file_name_urls))
        posts = self.load_posts_list(os.path.join(self.file_path_posts_folder, project_folder, page_folder_name))
        self.logger.info(f'Folders {page_folder_name}: find {len(posts)} posts and {len(urls)} ursl')

        # складываем  в масив для обработки
        # тут определяем наличие даты поста  date и category
        data = []
        if len(urls) >= len(posts):
            for i, p in enumerate(posts):
                d = {}
                d['nom'] = i + 1
                d['url'] = urls[i]

                title, post, date, category = self.get_post_title_data_category(p)
                d['post'] = post
                if title:
                    d['title'] = title
                if date:
                    d['date'] = date
                if category:
                    d['category'] = category
                data.append(d)
        else:
            for i, url in enumerate(urls):
                d = {}
                d['nom'] = i + 1
                d['url'] = url
                title, post, date, category = self.get_post_title_data_category(posts[i])
                d['post'] = post
                if title:
                    d['title'] = title
                if date:
                    d['date'] = date
                if category:
                    d['category'] = category

                data.append(d)
        return data

    def run(self):
        self.logger.info(f'Start posting')
        self.logger.info(f'Search folders ....')

        project_folders_name = []
        project_folders_names = [x for x in os.listdir(self.file_path_posts_folder)]
        self.logger.info(f'Find {len(project_folders_names)} folders for posts:')
        # тут убераем те которые в игноре
        for i,fn in enumerate(project_folders_names):
            if fn in self.white_foledrs_name:
                project_folders_name.append(fn)
            else:
                self.logger.info(f'folder {fn} not found in white list, skip')


        all_data = {}  # все данные по проектам
        for project_folder in project_folders_name:
            # это папки проектов, в них ищем папки страниц
            path = os.path.join(self.file_path_posts_folder,project_folder)
            page_folders_name = [x for x in os.listdir(path) if os.path.isdir(os.path.join(path,x))]
            page_data = {} # данные по страницам
            for page_folder_name in page_folders_name:
                page_data[page_folder_name] = self.get_page_folders(project_folder,page_folder_name)

            all_data[project_folder] = page_data


        for i,project in enumerate(all_data):

            for i, page in enumerate(all_data[project]):
                page_list = all_data[project][page]
                self.post_pages(project,page,page_list)

            self.create_project_log(project)

        self.logger.info('All folder compleate')
        input()

    def post_pages(self,project,page,data):
        pool = ThreadPool(self.thread_count)

        self.logger.info(f'{Fore.GREEN}~start posting folder {project}/{page} ...{Style.RESET_ALL}')
        results = pool.map(self.send_post_map, data)
        self.create_log(results, project,page)
        pool.close()
        pool.join()
        self.logger.info(f'{Fore.YELLOW}~posting folder {project}/{page} successfully {Style.RESET_ALL}')



def main():
    try:
        DEBUG = False

        logger = logging.getLogger('xmlrpc_poster')
        logger.setLevel(logging.DEBUG)

        fh = logging.FileHandler('log.txt')
        fh.setLevel(logging.DEBUG)

        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        if DEBUG:
            formatter = logging.Formatter('[LINE:%(lineno)d]#%(asctime)s: %(message)s')
        else:
            formatter = logging.Formatter('%(asctime)s: %(message)s')
        ch.setFormatter(formatter)
        fh.setFormatter(formatter)

        logger.addHandler(ch)
        logger.addHandler(fh)

        ###
        logger.info('Xmlrpc poster starting')
        poster = XmlrpcPoster()
        poster.run()



    except:
        logger.exception('main')

if __name__ == "__main__":
    main()