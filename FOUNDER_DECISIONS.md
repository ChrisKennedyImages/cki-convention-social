# Founder decisions

The source of truth. Every ruling Chris makes lands here, dated, in plain
words, with the code that enforces it named beside it. A decision changes
only when Chris says so.

## 2026-10-09: the start

- **Company name:** Event Caliber, for now. The name can change; it lives in
  one setting (`BRAND_NAME` in `.env`, default in `core/config.py`).
- **Legal entity:** CKI, LLC (`LEGAL_NAME`).
- **Repo:** a fresh private repo, `ChrisKennedyImages/cki-convention-social`,
  with its own history. Nothing from any other company's suite is referenced
  anywhere (`tests/test_banned_words.py`).
- **Conventions:** business, corporate and association conferences, conventions
  and trade shows, galas and award dinners. Fan conventions (comic, anime,
  gaming) are shot when someone asks by email, never advertised or named: off
  every public surface and out of the scout's search since 2026-10-12, their
  photos used as plain convention photos (no cosplay since 2026-10-11).
  Political work is taken when it comes, never what the company is positioned
  as.
- **Photo library:** Google Drive of chriskimages@gmail.com, read only, signed
  in as Chris (OAuth, `drive.readonly`).
- **Platforms:** Instagram, a Facebook Page and Pinterest, all through this
  company's own Buffer account.
- **Cadence:** one post a day.
- **Posting times:** left to the suite. Starting times, Eastern:
  Instagram about 11:30 on weekdays and 10:00 on weekends, Facebook about
  9:30, Pinterest about 20:30. These come from general industry data on
  engagement, not this account's own numbers; the suite moves toward what
  its own posts show once Buffer reports them.
- **Credits and consent:** one Google Sheet that Chris keeps.
- **Beyond social:** emails to event organizers (each sent only on Chris's
  Approve) and a website on a new domain, with mail sent from an address on
  that domain.
- **Brand:** the suite designs options for Chris to choose from; nothing is
  wired until he picks.
- **What the company sells:** full event coverage: backstage, green room,
  breakouts, before, during and evening events and dinners, portraits,
  exhibition halls and vendors, and immediate delivery of approved images to
  attendees, staff, speakers and presenters.
- **Prices:** vary by event and are not fixed. No post, email or page ever
  states a price; the call to action is a quote request
  (`ai/copy_rules.py`, rule `price`).

## 2026-10-09: second round

- **Official photographer:** none. Chris is not any event's official
  photographer, and there are no booked jobs yet: the company is starting
  back up after four years of caring for his mother. No copy may say or
  hint at an official role, a client list or past bookings that do not
  exist (`ai/copy_rules.py`; the calendar's official box stays unticked).
- **Umbrella:** everything runs under CKI, LLC. Event Caliber is its brand.
- **Domain:** eventcaliber.com, on Cloudflare (`BRAND_DOMAIN`).
- **Brand direction:** Lens (ring monogram, cobalt on graphite, Space
  Grotesk) (`BRAND_DIRECTION=lens`, `render/brand.py`).
- **Booking, built now:** a quote request form on eventcaliber.com that
  lands on the dashboard and on his phone; a drafted reply he edits and
  approves before it sends (he writes any price himself; the drafter never
  does); a public availability calendar that shows booked dates only, with
  no client or event names. The deposit link is built but OFF: no payment
  service yet.
- **Mail:** Cloudflare Email Routing forwards mail for the domain to his
  inbox; a sending service with SMTP sends from the domain.
- **Photo sorting:** Ollama on the Mini sorts the whole library (free). Claude
  looks again only at a photo picked for a post, as the final check for
  minors and personal details. A photo is postable only after that Claude
  check passes (`library/eligibility.py`).
- **Architecture photos:** his exterior and some interior architecture work
  can be used as full building and venue shots: in the daily feed one day a
  week, in the website portfolio, and behind promo graphics. Clearance is
  still per folder, by Chris; readable house numbers and street signs keep a
  photo out.

## 2026-10-10: what the building work may show

- **Architecture is buildings, not rooms.** Chris, after the first building
  contact sheet: the architecture work must **never** include empty rooms,
  bathrooms, closets or anything residential. The sheet of 2026-10-10 was
  full of all four, because the library's building work is largely
  commissioned real estate photography of apartments. **Bars are fine
  anywhere.** What is left is what the work was meant to be: building
  exteriors, and non residential interiors shown as architecture, such as a
  lobby, an atrium, a ballroom or event space, a bar, or a commercial or
  retail interior. Residential is asked as its own question, because a flat's
  hallway and a hotel's hallway are both corridors (`library/classify.py`
  `BANNED_SPACES`, `library/eligibility.py` `building_blocked`).
- **Addresses are fine on the building work.** Amending 2026-10-09: a street
  number or a street name is not a personal detail on Chris's architecture
  photographs, because they are public buildings and he already holds
  releases for them. On a photo of people it still blocks, because there the
  number says where somebody lives (`library/eligibility.py`
  `ADDRESS_DETAILS`). The sort still reads and records them either way.

## 2026-10-10: third round

- **Look:** not Lens. Black, white and greys with a touch of cyan. The first
  site was "not at all dynamic or edgy": rebuilt as a camera viewfinder
  (`site/theme.py`).
- **Logo: Aperture** (Chris, 2026-10-10). A C cut like an open aperture ring
  with a cyan point of light inside it; EVENT in white over CALIBER in grey,
  in Unbounded (`site/marks.py`, `render/brand.py`; `BRAND_MARK=aperture`,
  `BRAND_DIRECTION=aperture`).
- **Image metadata for search:** yes, our own words only (title,
  description, keywords, creator, copyright CKI, LLC, credit); never the
  camera's data or GPS (`render/meta.py`).
- **The crew grows:** Learner, Outreach, SEO, Scout, Chief of staff and Art
  director, each in dry run until switched on; anything that sends or posts
  still waits for Chris's Approve.

## 2026-10-09: going live

- "Merge and make sure live." The first milestone is merged into `main`. The
  site goes live before any photo is cleared: it is built without photos and
  the menu shows only the sections that exist; photos join on the next build
  once folders are cleared and the final check passes (`bin/ccs site build`).
- Going live is one command on the Mini, `scripts/go-live.sh`; it ends with
  `LIVE` only when every page and the booking API pass from the outside.

## 2026-10-11: the Mini updates itself

- "How the fuck do I work on this without a session in terminal on my mini."
  Chris chose auto-update: the updater agent checks GitHub every 10 minutes,
  runs the full suite on anything newly merged to `main`, and only on a green
  run fast-forwards the Mini and restarts the dashboard. Red tests, a checkout
  on another branch or with local changes hold it back. It ships in dry run
  like every agent; Chris switches it live on the Agents page. New service
  files still need one `scripts/go-live.sh` (his Mac password), flagged on the
  Agents page, never attempted.
- Every agent has a Run now button on the Agents page, so nothing day to day
  needs a terminal.
- `scripts/go-live.sh` brings the checkout up to date with GitHub itself before
  it installs anything (`bin/ccs sync`, the updater's way: tested first,
  fast-forward only) and clears the Agents page's ask once the services are
  installed (`bin/ccs launchd installed`). The evening of 2026-10-11 a go-live
  run on a checkout from before the last merge installed the old 6:00 draft
  schedule and said LIVE; `ccs status` now prints where the code stands against
  GitHub main, in capitals when it is behind.

## 2026-10-11: face match delivery, the photos, the look

- **Face match delivery is a lead selling point.** Chris: attendees scan the
  barcode on their lanyard or on posters around the event, fill in three
  short fields and take a quick selfie; every photo any of the photographers
  takes with their face anywhere in it is sent to them right away, with no
  wires. The convention staff or head decides before the event whether to
  offer that to attendees, or to keep it to staff, tailored so each staff
  member receives only the photos of the people they need, internally. The
  offer file, the caption brief, the outreach note, the quote reply and the
  site say it in those plain terms (`offer.json` `on_site_delivery`,
  `ai/claude.py`, `outreach/draft.py`, `site/build.py`).
- **The photos are original, no AI at all.** Every photo in the library is an
  original photograph; Chris and his brother own the rights to all of them.
  The suite never makes, alters or shows a generated image as if it were a
  photograph, samples included: design samples use his real photos.
- **The look moves.** After the first round of post designs ("You just made a
  fucking grid"), Chris sent the direction: photos as physical cards in depth
  and motion (a hand of cards fanned across the frame with the focused one
  lifted out, a spinning ring, a spotlight rail where the middle frame opens
  out with its caption, numbered folders), not flat tiles.

## 2026-10-11: only what Chris approves, and a dashboard he can find his way round

- **Only approved photos are ever used.** Chris: "When I go to the library, I
  only want to choose what I approve and if it's not approved then don't use it
  yet or at all." A photo is approved when he taps Use on it or clears its
  folder. Posts, the website and the design samples take approved photos only
  (`library/eligibility.py`, `render/design_samples.py`); unapproved photos show
  only where he chooses: Photos, To review, and the library report sheets.
- **Four tabs.** "The navigation is not intuitive or smart!" Today, Photos,
  Bookings and More, each with one row of its own pages; every folder page links
  back to the folder list and can clear or exclude the whole folder in place
  (`dashboard/app.py` `SECTIONS`).

## 2026-10-11: the daily post uses the new designs

- "Switch to new designs and it's ok to use 1 photo too sometimes." The daily
  draft rotates through the motion set: Monday spotlight (3 or more photos),
  Tuesday single, Wednesday (the building day) single, Thursday carousel (4 or
  more), Friday fan (5 or more), Saturday single, Sunday face match. A day whose
  design needs more approved photos than pass the final check is a single photo
  day. Every photo on a post is approved and passes the final check
  (`agents/content.py` `DESIGNS`).
- Reels stayed in the design samples until a music track was added (moved into
  the rotation the same day, below).

## 2026-10-11: reels, with music, in the rotation

- "Let's get the music and everything working (video format too)." Saturday is
  a reel once a music track is on (Photos, Design, Music for reels): the rooms
  reel and the face match reel take turns by week, on 4 to 6 approved photos
  that pass the final check, one per room before any room repeats. With no
  track Saturday stays a single photo: a silent reel is never made. A reel that
  cannot be made becomes a carousel of the same photos and says why
  (`agents/content.py` `DESIGNS`, `reel_kind`).
- The music is only ever a track Chris added with its record of where it came
  from and what it allows; it rides the reel faded in and out (`music.py`,
  `render/reel.py` `encode`).
- Instagram and Facebook get the reel as a video post with its cover; Pinterest
  gets a 2:3 card of the lead photo. Buffer's video format is not written from
  memory: before a reel is sent the publisher reads the video fields from
  Buffer's live schema, and if Buffer asks for anything the code cannot fill,
  nothing is uploaded and nothing is sent (`agents/publisher.py`,
  `buffer/payloads.py` `video_asset`). Like every post, a reel waits for
  Chris's Approve; the first one he approves is the live check of the format.

## 2026-10-11: one Anthropic key, Buffer ready to link, a dashboard that stays current

- **The Anthropic key is shared, by Chris's choice.** "Use my Anthropic key from
  [my other suite's] .env (DO NOT TOUCH ANYTHING IN THAT ENV)." This amends the
  brief's "no Anthropic key shared"; nothing else from that suite is used.
  `bin/ccs copy-key ANTHROPIC_API_KEY --from <that file>` only reads the file,
  checks it is byte for byte unchanged, saves the key in this suite's own
  `.env` and never prints it (`cli.py` `cmd_copy_key`). This suite's own spend
  still stops at `AI_MONTHLY_CAP_USD`.
- **Buffer plumbing before the account.** "A Buffer channel is not set up for
  this yet, but definitely get the plumbing in so we can just add it quickly
  when I do." The Buffer page (More, Buffer) takes it from a key to posting:
  find the channels, Use on each of this company's own accounts (nothing links
  by itself), the Pinterest board from Buffer's own list, and a check of the
  reel video format. A key that sees more than one Buffer organization posts
  nowhere until Chris chooses this company's (`buffer/client.py`
  `organization_id`, `dashboard/app.py`).
- **The dashboard stays current.** "Dashboard is still the old one." Every
  updater run asks the running dashboard which commit it serves and restarts it
  when it lags the checkout; if it still lags after one restart, Chris gets the
  one command that restarts it (`agents/updater.py` `ensure_dashboard`).

## 2026-10-11: the Photos tab, the Mini's disk

- **"Photos tab is dead."** Every visit loaded the whole library twice before
  showing 48 photos. The tab now reads one page from the database, with the
  same rules and order (`dashboard/app.py` `photo_page`, pinned against the old
  lists in `tests/test_photos_tab.py`). A page that fails says what failed and
  records it on the Agents page; when Drive is signed out the Photos tab says
  that is why the pictures do not load.
- **"The mini can't hold all these high res images."** Originals stay in Google
  Drive. The Mini keeps small previews, the full-size copy of each photo picked
  for a post, and the rendered posts; the company's bucket gets only the files
  of posts that go out. Every night the backup agent deletes the copies nothing
  needs any more, only inside the data folder, and says how much disk is free
  (`storage.py`).
- **Music in an .mp4.** An audio-only .mp4 is taken as a track; a file with no
  sound is refused (`music.py`).

## 2026-10-11: never which event, never who

- "Because A LOT of the images are ACU and CPAC (the same company) i want to
  make sure the captions don't say the specific event or person." No public
  word names the event, the organization behind it or any person, and no
  @handle tags anyone: not the captions, not the line printed on the post
  image, not the search fields inside the image files, not the website's photo
  text. They say the kind of event (a conference, a fan convention) and what
  the photo shows. The writers are never given the event's name or a credit;
  the copy rules block every name the suite knows (the two Chris named, every
  event name the sorting or the calendar recorded, everyone on the credits
  sheet), and both Approve and the publisher's last check enforce it
  (`ai/names.py`, `ai/copy_rules.py` rule `names`). Website text written
  before this is written again. Private mail to an organizer about their own
  event is not public copy and is not covered.

## 2026-10-11: no cosplay; captions built for search

- **No cosplay, anywhere.** "We are going to NOT do ANY COSPLAY ... erase that
  from everything." The offer, the website, the quote form, the caption and
  outreach prompts, the search text and the designs no longer mention it
  (pinned by `tests/test_seo_captions.py`). The photo sorter still tells
  costume photos apart, only so that none is ever used or offered for review
  (`library/eligibility.py` `NOT_OFFERED`).
- **Captions are built for search.** "Make sure the captions are SEO optimized
  painstakingly." Every post gets a search plan from what it shows (the kind of
  event, the room, the design; never a name): one search phrase, word for word
  in the first sentence of every caption and above Instagram's fold; related
  phrases in the body; the place when `SERVICE_AREA` is set (Keys page); five
  hashtags on Instagram and three on Pinterest, chosen in the code, specific
  first, none naming anyone; the quote link on Facebook and Pinterest; a pin
  title under 100 characters that opens with the phrase; alt text on every
  image where Buffer's live schema offers a field for it. A draft that misses
  is written once more with the misses named; after a second miss the
  template, which meets the plan by construction, stands in (`ai/seo_plan.py`,
  `agents/content.py` `write_captions`). Pins link to the quote page.

## 2026-10-11: the mock ups make themselves

- "Where are the mock ups with the approved images". The design samples on
  Chris's approved photos are made by themselves: the hourly scanner starts
  them whenever the approved photos they would use change. The Design card
  (Photos, Design) always says what happened: being made, ready, or not made
  and why, with how many approved photos are ready and how many the sorter
  still has to look at (it does approved photos first). A failure is also on
  the Agents page. The samples use every approved photo, not four per event
  (`render/design_samples.py` `auto`, `cli.py` `cmd_design`).

## 2026-10-11: what pings the phone

- "I haven't received any ntfy." Until now only the watchdog's alerts and the
  morning brief pinged. Now a post ready to approve pings with a link to the
  draft, a post that went out pings with a link to it, and the Keys page has a
  Send a test ping button that says whether the ping was sent or why not
  (`core/notify.py`, `agents/content.py`, `agents/publisher.py`). A ping needs
  `NTFY_TOPIC` on the Keys page and the agent live; the watchdog still pings
  failures within the hour.
## 2026-10-11: what the first real alerts found

- The watchdog's first pings (4:38 PM) named two faults. The dashboard ran out
  of file handles on the Photos tab (macOS gives a background process 256; 48
  previews at once need more): every process now raises its own limit at
  start, a preview is fetched from Drive once however many requests ask, at
  most six fetches run at a time, and the file is written whole before anyone
  reads it (`core/limits.py`, `dashboard/app.py` `cached_thumb`). The scanner's
  free sort pass ran for hours (about half a minute a photo, 500 a run) and
  nothing else of its hourly work happened meanwhile: a run now stops after
  `SCAN_BUDGET_MINUTES` (45) and sorts the rest next hour, approved folders
  first; the watchdog says "started … and has not finished" for a run still
  going, not "last ran" (`library/classify.py` `sort_pass`, `agents/watchdog.py`).

## 2026-10-11: what a photo shows is Claude's word, and Chris's

- "It calls a stage shot a portrait which, never can happen!" The free local
  sorter's shot type is a guess that reached the captions, the alt text and the
  image's search fields. Claude's final check, which already looks at every
  photo picked for a post in full, now says what the photo shows (a stage shot
  is stage_panel however close the framing) and that word replaces the guess
  everywhere it is read. On a draft each photo shows its word with a "Wrong?
  Fix and draft again" control: Chris's word is written everywhere, the draft
  is set aside and a new one is made at once (`library/classify.py`
  `final_check`, `set_shot_type`; `dashboard/app.py`).
- The learner weighs kinds of photo by what the post numbers say once Buffer
  reports them; it does not learn from corrections. A correction is applied,
  not learned.
- "Where I work is everywhere": `SERVICE_AREA` takes `nationwide`, a home base
  such as `Washington DC`, or both as `Washington DC, nationwide` ("Based in
  Washington DC, covering events nationwide.") (`ai/seo_plan.py`).
## 2026-10-11: buildings apart from events; the draft at 8

- "Architecture images should be separated from event/convention photos (even
  though we're using them for the same thing)." To review and Approved each
  show Events and Buildings as two lists with their own counts; a building is
  what the sorter called architecture (`dashboard/app.py` `SUBJECTS`).
- The daily draft runs at 8:00, not 6:00. It drafts the next day's post, so
  the hour changes nothing about when posts go out; it only sets when the
  draft and its ping arrive (`launchd/…content.plist.template`, one
  `scripts/go-live.sh` on the Mini to take effect).

## 2026-10-11: nothing includes anything

- On a draft that said conference photography "includes portraits like this
  one, shot on site in a few minutes. Colored gradient background, one chair,
  and a short line of attendees who all leave with a new headshot": "Suite
  wide - NOTHING INCLUDES ANYTHING!!!!! Don't ever say something you don't
  know or don't ask me about my own company!!!!" Public text says only what
  `offer.json` and Chris have stated. Nothing about what a service includes
  or comes with, how a shoot is set up, how long anything takes, what anyone
  leaves with, packages or turnaround. A detail the suite does not have is a
  question to him, never a sentence. The gate (`ai/copy_rules.py`, rule
  `claims`) blocks it on every surface: captions, the publisher door, the
  dashboard, outreach mail, quote replies, the site and the photo text; the
  writer is told the rule and the template describes only the coverage he
  listed.
- Then, sharper: "You need to keep to specifics and not talk about what is
  offered or what is a service, specifically in captions and social media or
  anything public. That's between the client and I!" A post is about the
  photo: what it shows, where in the event, the moment; never the company's
  services, coverage, delivery or what a client gets. Rule `offer` in the gate
  runs on every social surface (captions, the dashboard, the door, the cards,
  the reels); the writer's prompt no longer describes the company's services
  at all; the template says the scene and the byline; the cards say the room
  and what is shown. The face match post (Sundays) and the face match reel
  are retired: they explained the delivery service. Sunday is a single photo;
  the Saturday reel is the rooms reel. The website keeps the coverage list
  from `offer.json` that he saw go live; whether that stays is his to say.

## 2026-10-11: never a wedding; every photo judged on its own

- "The main photo when you open the website is from a damn wedding! That one
  needs to be the best of the best and not a wedding! Don't get stuck on
  certain photos. They get judge individually not against anything but
  itself." The local sorter had called a wedding reception an event. Now the
  sorter and Claude's final check both say what kind of occasion a photo is
  from (fan, business, wedding, private, unknown); a wedding or a private
  occasion is never a candidate, never eligible, never in the samples, never
  offered for review. The website picks each photo on its own merit: the
  strongest frame first (sharp, lit, a moment), a known conference or
  convention before an unknown kind; a photo Claude has not yet judged for
  its kind gets that check during the site build, up to twelve a build. The
  live daily draft re-checks every photo it picks, so a wedding never reaches
  a post either.

## 2026-10-11: the website's main photo, and no one event first on everything

- "The main photo needs to be the most colorful and dynamic photo - a wide
  stage panorama shot or a very powerful trump shot. And we need to not have
  CPAC and ACU the first thing on everything." The hero is chosen among the
  strongest eligible landscape frames by its own score: strength, colour and
  punch measured from the picture, a stage or panel, a wide frame
  (`site/build.py` `hero_score`). Chris can also pick it himself: Photos tab,
  Approved, "Site hero" on a photo; his pick wins while the photo is usable,
  and tapping it again hands the choice back. The site's grid and the design
  samples are spread across events, one per event before any event repeats.
  The daily draft already rotates events (`variety_days`).

## 2026-10-12: preferably not political

- "Preferably not political but will do if they're paying." Political work
  is taken when it comes; it is never what the company is positioned as. No
  public text, prompt or search names political conferences as the work:
  the site, the offer file, the quote form, the caption writer, the photo
  text and the scout say business, corporate and association conferences,
  conventions, galas and award dinners. The sorter still recognises a
  political conference as business work, so those photos are used like any
  other.

## 2026-10-12, late: the site goes live by itself; the panorama; no fan conventions; portraits are headshots

- "we will fix all tomorrow or do what you can without needing me to respond
  or terminal anything." So nothing here waits for a terminal:
  - **eventcaliber.com follows the code.** `ccs site deploy` is the build, the
    wrangler deploy with the untracked `wrangler.live.jsonc` that go-live
    leaves behind, and the check from outside (`site/deploy.py`). The updater
    runs it when a merge changes a site file, and once when the suite has never
    deployed the site; `scripts/go-live.sh` uses the same command. A deploy
    that fails is an error on the Agents page and is not retried by itself for
    that commit. **Publish the site**, a button on Photos, Approved, runs it from
    a phone after the hero or the approved photos change; the Website card
    there says what happened.
  - **The home page photo.** "the home page image is not the correct photo":
    the wide stage panorama he sent in the chat ships with the code as
    `site/hero.jpg` (re-encoded, no camera data) and is the hero whenever
    nothing has been sent from the phone; Claude checks it like any upload. A
    phone upload wins over it; Remove hands back to it.
  - **"We are going to get rid of 'fan conventions'."** Off every public
    surface: the offer file, the quote form, the captions and keywords, the
    photo text, the search metadata, the brand note, the scout's search brief
    (it leaves fan conventions out) and the dashboard's kind menus. His ruling,
    the same night: **"The fan photos go to plain conventions."** They are
    used like any convention photo, in posts and on the site, and every public
    word about them says convention. **"We will shoot a fan convention, but we
    are not going to advertise it or say it. People can email directly if they
    want us for that."** So the sorter keeps the tag (the photos can be told
    apart) and nothing is set aside; no public surface, search or outreach
    ever offers or names fan conventions.
  - **"Portraits and headshots are the same."** One coverage row, Portraits.
    One shot type, portrait; rows the sorter had called "headshot" are
    portraits (migration 0063), and every reader says Portrait.

## 2026-10-12, late: search engines

- "And yet no site map or Google search indexing." The sitemap and robots.txt
  have been built and checked from outside since 2026-10-09; what was missing
  is the telling. Now: the Google Search Console HTML tag goes on every page
  from the Keys page (`GOOGLE_SITE_VERIFICATION`), the sitemap carries each
  page's true last-changed date (a content record under the data root, never
  the build date), the first publish makes an IndexNow key (`INDEXNOW_KEY`,
  hosted at `/<key>.txt`) and every live publish tells Bing, Yandex and the
  other IndexNow engines which pages to read again (`seo/indexnow.py`). A
  ping that fails never fails a publish; the Website card says so. The one
  step only Chris can do, from his phone: add the property in Search Console,
  paste the tag, publish, press Verify, submit `sitemap.xml` (docs/SETUP.md,
  8a). Google is not in IndexNow and its Indexing API is not for this kind of
  site, so there is no way to make Google index it without that step.

## 2026-10-12, morning: captions mend themselves

- "the captions should auto correct themselves with the warnings they gave
  me before approval. I don't want to change any captions." A draft in the
  queue whose captions break a rule now (the rules grew after it was written)
  is rewritten by the suite, never by him: the content agent mends every open
  draft at the start of each run, the draft page mends one the moment he opens
  it, and Approve mends before it would ever refuse. The writer gets the
  rule's own words as the correction, twice, and the template stands in after
  that (`agents/content.mend_captions`). The page says what was rewritten and
  why; the old text is kept in the draft's record.

## 2026-10-12, morning: a morning with no draft is said out loud

- "the render didn't land this morning at 8am." A content run that drafts
  nothing used to end in a quiet summary line: no ping, no error, and the
  final check's two quiet reasons (the monthly AI cap, no key) returned
  nothing and said nothing. Now the run records the reason as an open error
  on the Agents page and pings the phone ("no post drafted for Tuesday", the
  reason, a tap to the Agents page), once per reason while it stands; the
  cap and a missing key are errors the moment they bite (`classify.look`).
  "Already drafted" stays quiet, since it is not a failure.

## 2026-10-12, morning: a name in the photo is fine

- Approved photos sat marked "shows personal details: document" and "screen"
  (a book cover with its author's name, a card in a portrait). "If they're
  wearing a name badge or there's a name in the photo it's fine to use." So a
  name badge, and the screens and documents the sorter flags at an event (a
  book cover, a program, a slide, signage: a name or a title), never keep a
  photo out of anything (`eligibility.NAME_DETAILS`), and the sorter and the
  final check are told that private information on a screen or paper means a
  message, an email or a form, never a title or a name. A plate, a house
  number or a street sign on a photo of people still keeps it out, as does
  anyone who may be under 18. Photos already flagged need no new look: the
  gate reads the stored flags with the new rule.

## 2026-10-12, late morning: the hero he sends is the hero

- "That's still not the ... landing page photo I uploaded on the dashboard."
  The photo he sends from the Photos page was held behind Claude's look (the
  under-18 rule on a crowd, or no look at all when the cap is reached), and
  the build fell back to its own pick while the card said why. That was the
  suite's design, not his law: his own photo, chosen by him, for his own
  site, is the hero, full stop (`site/hero.py`). Claude still looks at it
  once per file, for the alt text and a note on the card (anyone who may be
  under 18, a readable plate, a wedding), never to hold it back. Sending,
  removing or picking a hero on the dashboard publishes the site by itself,
  so there is no second button and no terminal.

## 2026-10-12, midday: exhibition halls, vendors and booths are one thing

- "Exhibition Halls, vendors and booths are all the same thing." One coverage
  row, Exhibition halls, on the site and the quote form; one shot type,
  `vendor_hall` (rows the sorter had called "booth" are the hall, migration
  0064), and every reader says Exhibition hall. Like portraits and headshots
  the same morning.

## 2026-10-12, afternoon: delivery is a feature; portraits are backstage, lit on site

- "Don't say instant delivery by 'facematch' and don't give the steps in
  which they [need] to do in order to receive the instant delivery. Again,
  too specific and it's a feature not the entire product." Nowhere public
  (the site, the quote reply, the organizer email): no "face match", no
  badge, no selfie, no steps. The site says photos can reach the people in
  them while the event is on, and that the photography is the work; the
  offer row is "Instant delivery during the event"; the quote question asks
  whether photos go out during the event and to whom.
- "A lot of the times the portraits are backstage for the event speakers and
  VIP etc, not the attendees. Some conventions want portraits for all
  attendees but that is kind of a different product. We do really stylized
  and professional portraits: all the lighting and color is done with
  onsite professional lighting (sometimes lighting we create or build
  ourselves) and color gels; no post editing is needed, or very limited."
  The site's Portraits row carries that in one line (the offer file's
  `note`); the portrait card says "Speakers and guests, backstage."; the caption
  writer is told the same and told never to say every attendee gets one.
  Attendee portraits are not advertised.

## 2026-10-13: never CPAC, never the ACU, never an affiliate

- "Also, never outreach to CPAC or the ACU or any affiliates! NEVER and
  that's a hard rule." The rule is code, not a row on a page
  (`outreach/compliance.never_contact`): the names he gave (`ai/names.ALWAYS`),
  the ACU's and CPAC's own domains, any host with "cpac" in its name, and any
  event or organizer named after them. The scout never stores such an event
  (`agents/scout.store`, `outreach/research.vet`), the outreach agent never
  drafts for one and refuses one at the door even when approved, the hand add
  on the Outreach page refuses it, a follow-up is refused, and the do-not-contact
  page says so with nothing to remove. Pinned in `tests/test_outreach.py`
  (`NeverContacted`, `Pages`) and `tests/test_scout.py`.

## 2026-10-13: every failure is said once, and out loud

Chris's answers for the roadmap, 2026-10-13: optimize for less of his time,
more inquiries and bookings, reliability, visibility and self-healing ("I need
to also run the other parts of the business too"); polish what exists; small
room for spend. The first batch makes the suite's own silences impossible:

- The watchdog alerts each recorded error on its own (keyed by its row, not
  its kind), so a second error of the same kind inside six hours is never
  swallowed; it hears its own errors; an error is marked as sent only when the
  mail or the push really went, and a mail that could not go is itself an
  error (`alert_mail`). The inbox and the chief are watched for missed runs.
- A phone ping that did not go is an `ntfy` error on the Agents page, said
  once while it stands (`core/notify.py`, every caller passes its connection).
- Markers that lied: the Buffer numbers are marked pulled only after a pull;
  the morning brief is marked sent only when the mail went (the phone is told
  once a day either way; a failed mail is a `brief_mail` error and the hourly
  run tries again); a site outage no longer stops the inbox from sending the
  replies he approved (`site_pull`); the design samples are recorded as made
  only when `ccs design` finishes, so a failed run is tried again next hour;
  a failed site deploy is tried again after thirty minutes, three times per
  commit, and the status says "try 2 of 3".
- The draft page never breaks when the rewrite cannot run: it says so, records
  a `mend` error once, and the next run tries again.
- The brief's disconnected-channel line opens the Buffer page; More has an
  Errors page.

## 2026-10-13: tomorrow's post always lands

Batch 2 of the roadmap: the one post a day is never lost to a blip.

- An Anthropic error in the final check, the caption writer or the art
  director is a reason, not a dead run: the final check's failure is said
  once (`final_check`) and the photo skipped; the writer's failure leaves the
  template (`captions`); the art director's failure sends the draft to Chris
  not reviewed (`art_director`). A dead Drive sign-in is a no-draft morning
  like any other, said and tried again.
- The draft window: the 08:00 job fires once, so the hourly watchdog starts
  the content agent again between 08:00 and 20:00 while tomorrow has no
  draft, up to four runs a day, when the last reason was passing, the last
  run crashed, or the inputs changed (`content.inputs_fingerprint`); the
  same reason on the same inputs waits. The phone hears each reason once a
  day. Past 20:00 with no draft, a loud alert once. No plist changed.
- A draft for Tuesday goes out Tuesday: the day it was drafted for is the
  floor for every network's slot (`pacing.plan not_before`); a time Chris
  sets still wins.
- Every design carries the hero as a 2:3 card for Pinterest.
- The door rewrites a caption that breaks a rule now (the template in dry
  run, so nothing is spent) and checks again, instead of sending the post
  back for him to approve again; one rewritten within the hour that still
  breaks goes back with the reason. No connected channel and no open day
  are errors on the Agents page, said once.

## 2026-10-13: silence never posts, and his Approve is honoured

Batch 3 of the roadmap. Chris's choices for it, 2026-10-13: posts and replies
he approved in dry run go out when the lane is switched live; silence is one
nudge after eight hours, never a post set aside; the photos stay as they are.

- A reject sets the post aside with him on the record
  (`rule_report.rejected_by = "chris"`), its photo sits out for the repeat
  window like the art director's (`content.recent_use`; the event and the
  people are not "used", since nothing of it aired), and the content agent
  is started at once so the day is drafted again: tomorrow's post when it is
  missing, else today's when today's was the one set aside
  (`content.set_aside_for`). Reject asks first. A post that already went
  out cannot be rejected.
- A draft waiting eight hours gets one push that opens it ("Still waiting:
  Tuesday's post. Nothing goes out unless you approve it."),
  `publisher.tend_drafts` on the ten-minute run; `rule_report.nudged_at`
  keeps it to one. It is never set aside, and the nudge goes whether the
  publisher is live or in dry run: the switch is about Buffer, the draft
  waiting for him is real either way.
- Switching a lane live (one, or everything at once) approves again what
  the dry run marked `would_publish` / `would_send`; the message says how
  many things go out. The publisher's door, `reply.ready_to_send` and
  `compliance.problems` check every one before it leaves. What was sent
  stays sent; back to dry run takes nothing back.
- A do-not-use entry sets the posts it touches aside
  (`rejected_by = "donotuse"`) with the reason and starts the content agent
  once, instead of leaving them in drafts for him to notice.
- An Approve can be taken back on the draft page ("Take back the
  approval") while the publisher has not picked the post up; a post Buffer
  already holds is pulled back from Buffer, not from here (roadmap 7.5).

## 2026-10-13: one tap on the phone

Batch 4 of the roadmap. Chris's choice for it: the morning ping carries the
rendered card and an Approve button; it ships on.

- Save is folded into Approve on the draft page, the quote reply and the
  organizer note: one form, two buttons ("Save", "Save and approve"). An
  edit is never lost on Approve; the gates (the suite's rewrite, the rules,
  the photos, the targets; `reply.ready_to_send`; `compliance.problems`)
  still hold on the way.
- Approve on the Queue list for a draft whose rules pass, photos are usable
  and art verdict is pass or not reviewed; a thumbnail opens the full card;
  the other captions unfold under it. Reject, Delete, Cancel, Exclude,
  Switch everything live, Remove and Spam ask first. Small buttons are 40 px
  tall.
- Approve from the ping (`core/approve_token`): the draft ping carries the
  card (`Attach`, fetched by the phone from the dashboard over Tailscale
  with the token, no login; nothing is copied to ntfy) and, when the art
  director passed the draft, an Approve button (an ntfy `http` action, a
  POST with a signed single-use token in its body) beside Open. The token
  is HMAC-SHA256 over the post id, its `updated_at`, an expiry (36 h) and a
  nonce kept in settings; a save or a rewrite kills it; a newer ping's
  token replaces an older one's; a GET on the address is a page with a
  button and approves nothing. The POST runs the page's own gates and
  answers in a sentence ("Approved post 7. It goes out Tuesday 11:30.").
  The eight-hour nudge carries the same.
- Words: the draft page never tells him to fix a caption; a photo approved
  by its folder says so instead of a no-op Undo.
- The Keys page holds every setting the code reads (posting times, the
  building day, the variety and repeat windows, the time zone, the brief
  hour, the Pinterest link, the scout region and horizon, the outreach
  caps), and a plain setting can be cleared back to its default. Secrets
  are replaced, never cleared from there.
- Google Drive sign-in from the phone: "Sign in to Google Drive" on the
  Drive page opens Google; the return page (127.0.0.1) does not load on the
  phone, so its address is pasted back on the Drive page. The same
  installed-app flow with PKCE as `bin/ccs drive login`, its state and
  verifier waiting in settings for 15 minutes; a foreign host, a stale
  sign-in and any scope but `drive.readonly` are refused. No Google console
  change.

## 2026-10-13: photos without the reload

Batch 5 of the roadmap: the Photos tab on the phone, in fewer taps, and the
site that follows them.

- A tap on Use, Don't use, Undo or Unblock answers in place (the page's own
  script asks for JSON; without it the form submits as before). Ticked
  photos take one tap: Use selected, Don't use selected.
- Exclude means out, fail closed: an excluded folder anywhere above a photo
  wins over a Use tapped on the photo, in the walker
  (`eligibility.clearance_of`), the one-pass map (`folder_decisions`,
  `decision_of`) and the Photos page's SQL. Don't use on the photo still
  wins over everything.
- A Blocked chip lists every photo marked Don't use, with Unblock; every
  card has Never use, which puts the photo on the do-not-use list and comes
  back to the same page.
- The site follows the photos: Use, Don't use, a folder decision, the hero
  pick and a do-not-use entry stamp `site.photos_changed_at`; ten minutes
  after the last change the updater's pass publishes by itself
  (`deploy.photos_pending`, inside `deploy.wanted`), with the same three
  tries half an hour apart as any deploy. The build holds the photos as of
  its start (`site.deployed_at`), so a tap during a build publishes again.
  Publish on the Website card starts it now instead of waiting.

## 2026-10-13: more bookings from the same site

Batch 6 of the roadmap. Chris's choices for it: the scout armed, around
Washington DC (DC, Maryland and Virginia); `chris@eventcaliber.com` on Google
Workspace ("I need a day to finish").

- The live Worker config follows the code: before every build
  `deploy.refresh_live_config` writes `wrangler.live.jsonc` from the
  committed `wrangler.jsonc` (read from git) with the booking database id the
  live file already holds; no id, no build. After every deploy the Worker's
  `NTFY_TOPIC` and `DASHBOARD_URL` secrets are put again from `.env`; a put
  that fails is an error on the Agents page, not a failed deploy.
- Pings end where he can act: the site's quote push opens the requests page
  (`Click`); a drafted reply pings once to its request (no name, email or
  phone in the push); drafted organizer notes ping once to Outreach; new
  scout finds ping once to Scout; a site that went live pings to the
  approved photos; design samples ping when ready.
- The scout is armed: `scout.dry_run` is switched off by migration 0070
  (one research call a week, about a dollar, inside the monthly cap); the
  region defaults to Washington DC, Maryland and Virginia when the Keys
  field is blank; "Search now" on the Scout page starts one run. Outreach
  stays as it was: it drafts, and a note leaves only on his Approve; that
  lane goes live only by his tap on the Agents page. The Outreach page
  shows the daily caps and the do-not-contact count.
- Mail is Google Workspace: `docs/SETUP.md` section 4 is the Workspace
  recipe (Google's DNS wizard for MX, SPF and DKIM; Email Routing off;
  `hello@` an alias if wanted; Keys, Mail = `smtp.gmail.com`, the address,
  a Google app password; Mail sent from = the address or a verified "Send
  mail as" alias). No code path changes; the proof is the test reply
  landing in his inbox once he finishes.

## 2026-10-13: see it: history, numbers, Today, the outside watch

Batch 7 of the roadmap.

- The live post's address rides with the history (`post_history.external_link`,
  migration 0071): the "posted" ping opens the post itself, and the Posts
  page links "Open on Instagram".
- A Posts page (a chip on Today): what went out, where it lives, the reach,
  engagement and clicks Buffer gives, the last 30 days and the last 12 weeks
  in plain tables (`buffer/metrics.summary`, `trend`, written for this and
  shown nowhere until now).
- Today says what needs him before the morning brief exists: `chief.needs`
  is the plain SQL half of the brief, shown at the top of the Queue page
  with the open-error count linking to the Agents page.
- The outside watch, free: the Mini checks in with the site hourly
  (`watchdog.check_heartbeat`, `POST /api/heartbeat`); the Worker's cron,
  every 30 minutes (`wrangler.jsonc` `triggers.crons`, on the Workers Free
  plan: five per account, read from developers.cloudflare.com on
  2026-10-13), rings the phone once, urgent, when two hours pass without a
  heartbeat, says "back" once when one returns, and says nothing while no
  heartbeat was ever posted. "Test the outside watch" on the Keys page asks
  the site to send that ping now, marked as a test. The one watch that does
  not live on the Mini.
- A scheduled post can be pulled back from Buffer ("Pull back from Buffer"
  on the draft page): deleted there one network at a time
  (`BufferClient.delete_post`, the mutation's input read from the live
  schema), then a draft again; what Buffer keeps stays scheduled, with the
  reason on the Agents page.

## 2026-10-13: leftovers

Batch 8 of the roadmap, the last one.

- A red update leaves the venv as it was (`agents/updater.update`): new
  requirements are installed before the tests, so when the tests fail on the
  Mini the checkout's own `requirements.txt` is installed again and the line
  says "requirements put back". A put-back that fails is an error on the
  Agents page (`update_requirements`) naming both commits, never a silent
  venv on the wrong code.
- Every paid Anthropic call holds its place on the ledger while it is in
  flight (`ai/spend.reserve`, `release`, `record(..., reservation=)`):
  the caption writer, the art director, the final check and the scout's
  research each reserve before the call (USD 0.15; the research call USD
  0.75), the reservation becomes the real row when the call settles, is
  released when the call fails, and is swept after 30 minutes when the
  process died. A reservation that would pass the monthly cap means no call,
  said as the cap is said (the final check records `ai_cap`; the scout's
  line says "would be passed by another research call"). Two agents can no
  longer each overshoot the cap by one call.
- Calendar attending/official stays out of the posts: no official events
  exist, and wiring it is the one way a caption could claim an affiliation
  (the affiliation rule above).

## 2026-10-13, evening: the Search Console value is taken in every form Google gives, and said when it is not

Chris: "It says Google search console tag is missing?" over a filled Keys
field. The build kept only the HTML tag or its content value and dropped
anything else without a word, so the Website card said "missing" and nothing
said why.

- `site/build.parse_verification` takes every form Search Console shows: the
  HTML tag, its content value, the TXT record of a Domain property
  (`google-site-verification=...`) and the HTML file's name or content; the
  file method writes its file at the root of the site.
- A value that is none of these is refused on the Keys page with the reason,
  shown on the Website card as "unusable" with the reason, and recorded once
  on the Agents page by a live build (`verification_tag`). Never a silent
  blank.
- A saved Search Console value makes the site republish itself ten minutes
  later, like a photo change (`site.tag_changed_at`); no Publish tap.
- The check from outside after every publish looks for the tag on every live
  page (or the file at the root), where Search Console looks; a page without
  it fails the publish and the card says so.
- A property Search Console verified by itself (Chris: "it never asked for a
  html tag for ownership when I verified"; a Domain property through
  Cloudflare's DNS) needs nothing on the Keys page: the card says so in plain
  words, with no badge. An empty field is not a fault.

## 2026-10-14: his brothers' galleries

Chris: "Can you pick up shared galleries too on drive? Several have me and
my brothers images." They live under "Shared with me" (his brother's own
Drive, shared to the account); every shared folder with photos is taken in.

- Drive lists only what was shared directly, so the scanner now walks each
  shared gallery for the photos inside it (`drive/scan.walk_shared`,
  `DriveReader.children`), in the weekly full pass and, for a gallery shared
  since the last run, within the hour (`incremental` lists the shares again).
  Reads only, before any transaction opens; the scope stays `drive.readonly`.
- A shared gallery is a top folder of its own, "Shared with me/<name>",
  cleared like any folder; a folder shared on its own inside a gallery he
  can see keeps its place under it, so clearing the gallery reaches it. A
  single photo shared on its own has no folder and is cleared only by hand.
- Nothing in a shared gallery is used until he clears the folder or the
  photo; an excluded gallery keeps its photos out. The same law as his own.
- Who shared it is kept as a name (`drive_folders.shared_by`), shown on the
  Folders list, the folder page and the Drive page. No address is asked for
  or stored.
- In passing: a photo loose at the top of My Drive no longer gets a "(new
  folder)" stub row on a changes run (the root ids are remembered).

## 2026-10-14: no picture follows the mouse

Chris, on the site from his computer: "It just follows my mouse (that
picture)." The coverage peek (a photo that trailed the cursor while the
mouse was over the Coverage list) is removed from the home page, its style
and its script. The cursor ring and the hero's web are the only things that
answer the pointer; nothing else on the site moves with the mouse.

## 2026-10-14: every approved photo gets its turn

Chris: "You also keep using the same fucking photos for everything when I
have approved at least 40 by now." Every picker ranked the approved pool by
the same score and took the top of it: the daily draft (held back only by
the repeat window), the website's grid and venues, the design samples. The
strongest few therefore won on every surface, and a newly approved photo
below them was never seen.

- The rule: with N approved photos, every surface uses all N before any
  comes round again. Each picker draws the least recently used photo first,
  on any surface (a photo in yesterday's post is at the back of the line
  for tonight's site build too), and the quality order only breaks ties.
  Quality never decides on its own.
- The memory is one table, `photo_use` (photo, surface, which post, build
  or samples folder, when), written where a surface commits to a photo:
  every draft (a dry-run draft too, since one approved in dry run goes out
  when the lane is switched live; the art director's turned-back draft too,
  it sat out before), every site build that is not a preview, every set of
  samples. The drafts made before the table existed were filled in from the
  queue once, so the day this landed the site and the samples already
  preferred what no post had shown.
- The repeat window (`PHOTO_REPEAT_DAYS`, Keys page) stays as the floor: a
  photo on a draft sits out for the window whatever the rotation says. With
  about 40 approved photos and a 180-day window the drafts run dry in a few
  weeks; the rotation makes a shorter window safe, and the window is his to
  set.
- The hero he picked or sent is never rotated away. The grid and the venues
  under it rotate on every publish.
- The samples are made again when the approved photos change (one
  approved, one taken away) or the words on the cards do, never because
  the six they would draw rotated (that would remake them every hour).
- A draft set aside because he corrected a shot word gives its photos back
  (the same photo leads the new draft, with the right words).
- The Photos page, Approved, says under each photo "used N times, last on
  <date> (post, site, samples)" or "never used yet"; the content run's line
  on the Agents page says which photo led and why ("never used before; 40
  ready, least recently used first").

## Standing rules from the brief

- CPAC, the ACU and their affiliates are never contacted, by code
  (2026-10-13, above).

- Nothing publishes without Chris's Approve on the dashboard, until he says
  otherwise. Every agent that sends or publishes starts in dry run
  (`core/settings.py`).
- Nothing in Drive is ever modified, moved, renamed or deleted
  (`drive/`, pinned by `tests/test_drive_readonly.py`).
- No photo is eligible until Chris clears its folder or the photo itself.
  Never post anyone who may be a minor. A do-not-use list is honoured
  everywhere.
- Never claim to be a convention's official photographer or any affiliation
  unless Chris confirms it for that event (`ai/copy_rules.py`, rule
  `affiliation`).
- Captions and copy: plain, short sentences, no dashes, never promise what
  the system does not do today.
