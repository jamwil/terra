# terra
Terra allows for geographic search of Alberta Land Titles. One can easily identify all of the recent transactions for a given geographic area, anywhere within the province.

Care must be taken to specify small search areas so as to not overload the server with requests. General rule of thumb is to limit primary and secondary market searches to individual neighbourhoods or a small set of neighbourhoods. Towns with populations under 10,000 or so can generally be searched in one pass. The system works by breaking the search area into manageable chunks in a grid and searching each resulting quadrant. One can increase the quadrant size to make fewer server requests, though if the quadrant size is too large Spin will fail to complete the request. Requests are heavily rate limited to prevent abuse.

Before loading the virtualenv, check running jobs for chrome webdriver. If it's not running, execute `nohup ./start-chrome.sh $` from the terra folder and send it to the background.

---

todo
- [ ] Fix bug with first title mapped now geocoding property
- [ ] Usually still getting one or two duplicates
