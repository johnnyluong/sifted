<answers>
{% for a in answers %}- {{ a.question }}
  {{ a.answer }}
{% endfor %}</answers>
{% if kept_anyway %}
Posts Sift scored below their line that they kept anyway, and why:
<kept_anyway>
{% for k in kept_anyway %}- "{{ k.title }}": {{ k.reason }}
{% endfor %}</kept_anyway>
{% endif %}
