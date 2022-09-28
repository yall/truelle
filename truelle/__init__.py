from typing import List, Dict, Union, Iterable
import hashlib
import os
import urllib
import pickle
import parsel
import requests
import logging

class Request:
    
    def __init__(self, url:str, method:str="get", callback=None):
        self.url = url
        self.method = method
        self.callback = callback
    

class Response:
    
    def __init__(
        self,
        url: str,
        status: int,
        headers: Dict,
        body: bytes,
        text: str,
        request: Request):
        self.url = url
        self.status = status
        self.headers = headers
        self.body = body
        self.text = text
        self.request = request
        self._cached_selector = None
        
    @property
    def selector(self):
        if self._cached_selector is None:
            self._cached_selector = parsel.Selector(text=self.text)
        return self._cached_selector
    
    def css(self, query):
        return self.selector.css(query)

    def urljoin(self, url):
        return urllib.parse.urljoin(self.url, url)
    

class CancelRequest(Exception):
    pass

    
class Middleware:
    
    def process_request(self, request: Request) -> Union[Request, Response]:
        """
        raise CancelRequest to cancel
        return a modified request to next middleware
        return response to stop processing (next middlewares won't be called)
        """
        return request
    
    def process_response(self, response: Response) -> Union[Request, Response]:
        return response
    


class HttpCacheMiddleware(Middleware):
    """
    
    Limitations:
        - no validation policy
        - dummy fingerprint implementation (params order, fragments...)
    """
    
    def __init__(self, settings={}):
        if settings.get("HTTP_CACHE_ENABLED", False):
            self._enabled = True
            self._dir = settings.get("HTTP_CACHE_DIR", ".truelle")
            self._fingerprinter = RequestFingerprinter()
        else:
            self._enabled = False

    def _store_response(self, request: Request, response: Response):
        fingerprint = self._fingerprinter.fingerprint(request)
        dir = os.path.join(self._dir, fingerprint[0:2])
        os.makedirs(dir, exist_ok=True)
        with open(os.path.join(dir, fingerprint), 'wb') as f:
            pickle.dump(response, f)
        
    def _retrieve_response(self, request: Request) -> Response:
        fingerprint = self._fingerprinter.fingerprint(request)
        path = os.path.join(self._dir, fingerprint[0:2], fingerprint)
        if not os.path.exists(path):
            return None
        with open(path, 'rb') as f:
            return pickle.load(f)
    
    def process_request(self, request: Request) -> Union[Request, Response]:
        if not self._enabled:
            return super().process_request(request)
        
        cached_response = self._retrieve_response(request)
        if cached_response:
            return cached_response
        
        return request
        
    def process_response(self, response: Response) -> Union[Request, Response]:
        if not self._enabled:
            return super().process_response(response)
    
        self._store_response(response.request, response)
        return response


class DeduplicationMiddleware(Middleware):

    def __init__(self, settings={}):
        self._seen_requests = set()
        self._fingerprinter = RequestFingerprinter()
    
    def process_request(self, request: Request) -> Union[Request, Response]:
        fingerprint = self._fingerprinter.fingerprint(request)
        if fingerprint in self._seen_requests:
            raise CancelRequest()
        self._seen_requests.add(fingerprint)
        return request


class MiddlewareChain:

    def __init__(self, downloader, middlewares):
        self._downloader = downloader
        self._middlewares = middlewares

    def process(self, request: Request) -> Union[Request, Response]:
        ret = request
        backwards_chain = []

        for i, middleware in enumerate(self._middlewares):
            backwards_chain.append(middleware)
            ret = middleware.process_request(ret)
            if isinstance(ret, Response):
                break
        
        if isinstance(ret, Request):
            ret = self._downloader.fetch(ret)
        
        for middleware in backwards_chain:
            ret = middleware.process_response(ret)

        return ret


class Downloader:
    """HTTP Downloader only for know. 
    
    Limitations:
        - Using requests as HTTP client.
        - Cookies: using a requests Session to store cookies
    """
    def __init__(self):
        self._session = requests.Session()
        
    def _build_response(self, req: Request, res: requests.Response) -> Response:
        return Response(
            res.url,
            res.status_code,
            dict(res.headers),
            res.content,
            res.text,
            req
        )
    
    def fetch(self, request: Request) -> Response:
        req = requests.Request(request.method, request.url).prepare()
        res = self._session.send(req)
        return self._build_response(req, res)
    

class Spider:
    
    start_urls = []
    
    def start_requests(self) -> List[Request]:
        return [ Request(url) for url in self.start_urls ]
    
    def parse(self, response: Response):
        ...
    
    def crawl(self, settings={}):
        crawler = Crawler(self, settings=settings)
        return crawler.crawl()

class RequestFingerprinter:

    def fingerprint(self, request: Request) -> str:
        b = request.url.lower().encode('utf-8')
        hash_object = hashlib.sha1(b)
        return hash_object.hexdigest()
    

class Scheduler:
    
    def __init__(self):
        self.requests = []
    
    def add_request(self, request: Request):
        self.requests.append(request)
        
    def next_request(self) -> Request:
        if len(self.requests) == 0:
            return None
        return self.requests.pop(0)
    
    def has_next(self):
        return len(self.requests) > 0
    
    
class Crawler:
    
    def __init__(self, spider, settings={}):
        self._spider = spider
        self._settings = settings
        self._scheduler = Scheduler()
        self._middleware = MiddlewareChain(
            Downloader(),
            [ 
                DeduplicationMiddleware(settings),
                HttpCacheMiddleware(settings) 
            ]
        )
        
    @staticmethod
    def to_iterable(result):
        if isinstance(result, (str, dict, bytes)):
            return [ result ]
        if isinstance(result, Iterable):
            return result
        return []

    def crawl(self):
        
        start_requests = self._spider.start_requests()
        
        for req in start_requests:
            self._scheduler.add_request(req)
        
        while self._scheduler.has_next():
            req = self._scheduler.next_request()
            if not req.callback:
                req.callback = self._spider.parse
            
            try:
                resp = self._middleware.process(req)
            except CancelRequest as e:
                continue

            if isinstance(resp, Request):
                self._scheduler.add_request(resp)
                continue

            if not isinstance(resp, Response):
                logging.error("Object should be a response %s" % str(resp))
                continue

            parsed_results = req.callback(resp)
            
            # Yield items and requeue requests
            for result in self.to_iterable(parsed_results):
                if isinstance(result, Request):
                    self._scheduler.add_request(result)
                    continue
                # item
                yield result
            
        