# Truelle



Truelle - "trowel" in french - is a tiny web scraping library, inspired by the great [Scrapy](https://scrapy.org/) framework, 
depending only on [Requests](https://requests.readthedocs.io/en/latest/), and [Parsel](https://github.com/scrapy/parsel) libraries.

Truelle only offers a sequential request processing, and returns items directly
It's intended to be embedded in tiny scripts. Spiders aims to be compatible with Scrapy spider and easily switch to a Scrapy.

## Install

    pip install truelle

## Get started

1. Create a Spider

```python
from truelle import Spider

class MySpider(Spider):
    start_urls = [ "https://truelle.io" ]
    
    def parse(self, response: Response):
        for title in response.css("h1::text").getall():
            yield { "title": title }
            
spider = MySpider() 
```

2. Then get your items back...

... in vanilla Python:
           
```python
for item in spider.crawl():
    do_something(item)
```

... in a Pandas dataframe:

```python
import pandas as pd
my_df = pd.DataFrame(spider.crawl())
```

## Custom settings

```python
def custom_fingerprint(request):
    return "test"

custom_settings = {
    "HTTP_CACHE_ENABLED": True,
    "REQUEST_FINGERPRINTER": custom_fingerprint,
    "HTTP_PROXY": "http://myproxy:8080",
    "HTTPS_PROXY": "http://myproxy:8080",
    "DOWNLOAD_DELAY": 2
}

spider.crawl(settings=custom_settings)
```
