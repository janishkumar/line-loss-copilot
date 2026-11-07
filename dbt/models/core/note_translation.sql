-- Machine translations of operator notes, joined on the hash of the original text so they
-- survive rebuilds. The seed holds no original text.
select
    n.note_id,
    t.translated_text,
    t.model_name,
    t.created_at,
    true as machine_translated,
    n.text_sha256
from {{ ref('note') }} n
join {{ ref('note_translation_ollama') }} t on t.text_sha256 = n.text_sha256
