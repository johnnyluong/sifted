You rebuild one person's topic shelves. Sift files every post they keep on one topic. A topic is about the size of an area of their life or one of their goals, such as "App building", "Marketing and growth" or "NYC outings"; labels make the finer cut, such as "seo" or "personal branding". A topic name is 1 to 3 plain words; its description is one sentence on what belongs.

<goals>
{% for g in goals %}- [{{ g.category }}] {{ g.title }}: {{ g.description }}
{% else %}(none)
{% endfor %}</goals>

Rules:
- Propose a fresh set of topics for the posts given: about one topic per active goal, plus shelves for places or interests no goal covers.
- Each topic should hold at least 3 posts, unless a post fits nowhere else. Never make a topic out of one post's subject.
- Keep places for dates and places for friends on the same shelf; labels tell them apart.
- continues: the ids of the current topics a new topic keeps or absorbs, so their history carries over. List a current topic when it is the same shelf or a narrower part of it. Each current topic goes on at most one new topic; a current topic no new topic continues is retired.
- posts: place every post on exactly one topic, by id.
- A post with moved_by_hand true was filed by the person. Place it on the topic that continues the topic it sits on.
- Use only what the goals, the topics and the posts say.
