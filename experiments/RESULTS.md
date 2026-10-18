# Fallback-chain experiment results

- Run: https://github.com/aliwaziri10/marius-command-center/actions/runs/39128382109
- Commit: 9c720a2330e94975f55b57ba02d36fdef88046dd
- Time: 2026-10-18 12:42:13 UTC

| Source | Result |
|---|---|
| Pixabay video | PASS |
| Pexels video (optional) | SKIPPED |
| NASA Image and Video Library | PASS |
| Internet Archive | PASS |
| Wikimedia Commons | PASS |
| Agnes quick check | SKIPPED |

## Pixabay video: PASS

- short keywords: q='ocean waves' HTTP 200, totalHits=500, returned=3, rate-limit headers {'X-RateLimit-Limit': '100', 'X-RateLimit-Remaining': '99', 'X-RateLimit-Reset': '60'}
- long prompt-like: q='Wide cinematic shot of ancient stone ruins at golden hour, slow drone push in, dust in the air, no p' HTTP 200, totalHits=500, returned=3, rate-limit headers {'X-RateLimit-Limit': '100', 'X-RateLimit-Remaining': '98', 'X-RateLimit-Reset': '60'}
- first hit id=283533 duration=40s small=960x540
- CREDIT: Video by BlenderTimer on Pixabay, https://pixabay.com/videos/id-283533/ (Pixabay Content Licence, https://pixabay.com/service/license-summary/)
- file check HTTP 206, content-type video/mp4, first bytes read 1024

Raw excerpt:
```
{"total":17033,"totalHits":500,"hits":[{"id":283533,"pageURL":"https://pixabay.com/videos/id-283533/","type":"film","tags":"wave, breaking, sea, ocean, water, coast, slow motion, slowmo","duration":40,"videos":{"large":{"url":"https://cdn.pixabay.com/video/2025/06/03/283533_large.mp4","width":1920,"height":1080,"size":38263129,"thumbnail":"https://
```

## Pexels video (optional): SKIPPED

- no PEXELS_API_KEY in this run

## NASA Image and Video Library: PASS

- search HTTP 200, returned=3
- first item nasa_id=ARC-20201026-AAV3272-SOFIA-MoonWater-Shareable-NASAWeb title='SOFIA Discovers Water on a Sunlit Surface of the Moon' center=ARC
- mp4 variants found: ['orig.mp4', 'large.mp4', 'medium.mp4', 'mobile.mp4', 'preview.mp4', 'small.mp4']
- CREDIT: NASA, SOFIA Discovers Water on a Sunlit Surface of the Moon (nasa_id ARC-20201026-AAV3272-SOFIA-MoonWater-Shareable-NASAWeb). NASA media usage guidelines: https://www.nasa.gov/nasa-brand-center/images-and-media/ . Licence per item UNVERIFIED.
- file check HTTP 206, content-type video/mp4, first bytes read 1024

Raw excerpt:
```
{"collection":{"version":"1.1","href":"http://images-api.nasa.gov/search?q=moon+surface&media_type=video&page_size=3","items":[{"href":"https://images-assets.nasa.gov/video/ARC-20201026-AAV3272-SOFIA-MoonWater-Shareable-NASAWeb/collection.json","data":[{"center":"ARC","date_created":"2020-10-26T00:00:00Z","description":"Scientists using NASA’s tele
```

## Internet Archive: PASS

- search HTTP 200, returned=3
- identifier=AboutBan1935 title='About Bananas' licenseurl=http://creativecommons.org/licenses/publicdomain/ rights=None
- CREDIT: Internet Archive, About Bananas, https://archive.org/details/AboutBan1935 (licence: http://creativecommons.org/licenses/publicdomain/)
- mp4 file AboutBan1935.mp4 size=68512128 format=h.264
- file check HTTP 206, content-type video/mp4, first bytes read 1024

Raw excerpt:
```
{"responseHeader":{"status":0,"QTime":33,"params":{"query":"collection:prelinger AND mediatype:movies","qin":"collection:prelinger AND mediatype:movies","fields":"identifier,title,licenseurl","wt":"json","sort":"downloads desc","rows":3,"start":0}},"response":{"numFound":10461,"start":0,"docs":[{"identifier":"AboutBan1935","licenseurl":"http://crea
```

## Wikimedia Commons: PASS

- search HTTP 200, returned=3
- title='File:Mount Merapi Landscape.webm' mime=video/webm size=1920x1080
- CREDIT: File:Mount Merapi Landscape.webm by Joaquim Baeta, licence CC BY 4.0, attribution required: true, https://commons.wikimedia.org/wiki/File:Mount_Merapi_Landscape.webm
- file check HTTP 206, content-type video/webm, first bytes read 1024

Raw excerpt:
```
{"batchcomplete":true,"continue":{"gsroffset":3,"continue":"gsroffset||"},"query":{"pages":[{"pageid":125913691,"ns":6,"title":"File:Mount Merapi Landscape.webm","index":3,"imagerepository":"local","imageinfo":[{"size":69448331,"width":1920,"height":1080,"duration":60.488,"url":"https://upload.wikimedia.org/wikipedia/commons/4/45/Mount_Merapi_Lands
```

## Agnes quick check: SKIPPED

- experiments/PROBE_AGNES not present, no probe sent
