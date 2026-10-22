"""Pre-turn risk gate.

Two layers, combined conservatively:
  1. `RulesGate`: deterministic regexes (English / Hinglish / Devanagari) that run on every message and cannot be
     talked out of by a prompt. They deliberately over-trigger: a false escalation costs one gentle check-in; a miss
     can cost a life.
  2. `ClaudeRiskClassifier`: claude-haiku-5-5 with the classifier prompt from the plan (JSON output). It may RAISE
     the level or add categories; it can never lower what the rules found.

Levels: NONE < ELEVATED < IMMINENT.  When unsure, escalate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from .prompts import CLASSIFIER_PROMPT, CLASSIFIER_SCHEMA, RISK_LEVELS

NONE, ELEVATED, IMMINENT = RISK_LEVELS
_RANK = {NONE: 0, ELEVATED: 1, IMMINENT: 2}


def max_level(*levels: str) -> str:
    return max(levels, key=lambda l: _RANK.get(l, 0)) if levels else NONE


@dataclass
class RiskAssessment:
    level: str = NONE
    categories: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    source: str = "rules"            # rules | classifier | combined
    confidence: float = 1.0
    rules_categories: list[str] = field(default_factory=list)   # what the deterministic layer itself found

    def acted(self) -> bool:
        """Has the person actually done something (ingestion, cutting now, on a ledge, medical emergency)?
        The regexes are precise about this; the classifier's categories are not trusted for it when the message is a
        method *question* (fiction / research / hypothetical), which must never open with the ambulance script."""
        acted_cats = {"in_progress", "overdose_substance", "medical_emergency"}
        if set(self.rules_categories) & acted_cats:
            return True
        return bool(set(self.categories) & acted_cats) and not self.has("method_request")

    @property
    def is_flagged(self) -> bool:
        return self.level != NONE

    def has(self, *cats: str) -> bool:
        return any(c in self.categories for c in cats)


# --------------------------------------------------------------------------------------------
# Patterns. Each category -> list of regexes (case-insensitive). Devanagari has no \b word boundaries, so those
# patterns are written without them.
# --------------------------------------------------------------------------------------------
_P: dict[str, list[str]] = {
    # ---- suicidality ------------------------------------------------------------------------
    "suicidal_ideation_passive": [
        r"\b(wish|wished|wishing) (i|that i) (were|was|wasn'?t|weren'?t|could) (dead|gone|not here|not alive|never born|disappear|just disappear|here|alive)\b",
        r"\bwish i (could|would) (disappear|just disappear|vanish|not wake up|never wake up|sleep forever|go to sleep and not wake)\b",
        r"\b(don'?t|do not|dont) want to (be here|be alive|wake up|exist|live anymore|live any more|go on|carry on)\b",
        r"\b(tired of|sick of|done with|fed up (of|with)) (living|life|everything|being alive|this life|it all)\b",
        r"\b(no (point|reason|use) (in|of|to) (living|life|going on|being here|waking up)|what'?s the point of (living|life|anything|going on))\b",
        r"\b(better off|happier) without me\b",
        r"\b(i am|i'?m) (just )?(a )?burden (to|on) (everyone|them|my family|people)\b",
        r"\b(nobody|no one) would (miss me|care if i (died|was gone|disappeared|wasn'?t here))\b",
        r"\bhope i (don'?t|never) wake up\b",
        r"\b(feel like|want to|wanna|just want to|would love to|wish i could) (disappear|disappearing|vanish|vanishing|not exist|cease to exist|stop existing|fade away|go to sleep forever|sleep forever|never wake up)\b",
        r"\b(don'?t|can'?t|cannot|do not) see (the|any) (point|reason|sense) (of|in|to) (anything|living|life|going on|it all|this|carrying on|continuing|waking up)( anymore| any more)?\b",
        r"\bgayab ho (jaun|jaaun|jau|jana chahta|jana chahti|jaana chahta|jaana chahti)\b",
        r"\b(jeene ka|zindagi ka|zinda rehne ka) (koi )?(matlab|maksad|faida|point) (nahi|nhi)\b",
        r"\b(jeena nahi|jeena nhi|jine ka mann nahi|jeene ka mann nahi|jeene ki (ichha|iccha) nahi|ab jeena nahi)\b",
        r"\b(kaash|kash) (main|mai|mein) (na hota|na hoti|mar jaun|mar jau|gayab ho jaun|kabhi paida na)\b",
        r"\b(sab|sb) (khatam|khatm|khtm) ho (jaye|jaaye|jae)\b",
        r"\b(sabko|sab ko|ghar walon ko|mere bina) (mere bina )?(aaram|sukoon|chain|better) (hoga|milega|rahega)\b",
        r"\b(mere bina sab|sab mere bina) (theek|better|khush|acche) (honge|rahenge|hain)\b",
        r"\b(main|mai|mein) (sab pe|sab par|sabke liye|family pe|ghar walon pe) (bojh|burden) (hoon|hu|hun|ban gaya|ban gayi)\b",
        r"\bbojh (hoon|hu|hun|ban gaya|ban gayi)\b",
        r"(जीना नहीं चाहत|जीने का (कोई )?(मतलब|मकसद) नहीं|काश मैं (न होत|मर जा)|सब खत्म हो जाए|सब ख़त्म हो जाए|मेरे बिना (सब|सबको) (बेहतर|सुकून|आराम)|मैं (सब पर |सबके लिए )?बोझ (हूँ|हूं))",
    ],
    "hopelessness": [
        r"\b(i('m| am) (just |such |a |an |totally |completely |a complete |a total )*(worthless|useless|a failure|failure|pathetic|waste of (space|a life|oxygen|everyone'?s time)|good for nothing|unlovable|a nobody|nothing to anyone)|everyone (hates|despises) me|nobody (loves|cares about|wants|needs) me|no one (loves|cares about|wants|needs) me|main (ek |bilkul )?(nakama|nakaara|nikamma|nikammi|bekaar|failure|kisi kaam ka nahi|kisi kaam ki nahi|kisi layak nahi) (hoon|hu|hun)|mujhe koi (pasand|pyaar|pyar|chahta|chahti) nahi (karta|karti|hai))\b",
        r"\b(no hope|hopeless|nothing will (ever )?(change|get better|work out)|can'?t (go on|take (it|this) anymore|do this anymore|carry on like this|see a way out)|there'?s no way out|no way out)\b",
        r"\b(i give up on (life|everything)|i('ve| have) given up|what'?s the use)\b",
        r"\b(koi umeed nahi|koi ummeed nahi|ab (aur )?nahi (ho sakta|hoga|hota|hopayega)|bardasht nahi (hota|ho raha|hoga)|ab aur nahi|koi rasta nahi|kuch nahi badlega|kabhi theek nahi hoga|har li|haar gaya|haar gayi|haar maan li)\b",
        r"(कोई उम्मीद नहीं|कोई रास्ता नहीं|अब (और )?नहीं (हो सकता|होगा|सह सकत)|बर्दाश्त नहीं|कुछ नहीं बदलेगा|हार (गया|गयी|गई|मान ली))",
    ],
    "suicidal_ideation_active": [
        r"\b(i('m| am|'ve been| have been) (feeling |so |very |really )?suicidal|suicidal (thoughts?|feelings?|ideation|urges?)|(commit|committing|do|attempt|attempting|complete) suicide|suicide (kar|karna|karunga|karungi|karne|karlu|kar lun|kar loon)|thinking (about|of) suicide|suicide (is|seems|feels|looks) (like )?(the|my) (only|best|easiest)|feel(ing)? suicidal)\b",
        r"\b(kill|killing|end|ending|take|taking) (myself|my life|my own life|it all)\b",
        r"\b(want|wanna|wanted|going|gonna|ready|thinking|think|thought|planning|decided) (to |about )?(die|dying|kill myself|end (it|it all|my life|everything)|be dead|not be alive)\b",
        r"\b(want|wanna|wish) to (die|be dead|end it)\b",
        r"\bend (it all|my life|everything|this life|things) (tonight|today|now|soon|for good)?\b",
        r"\b(hurt|harm) myself (badly|seriously|for good|permanently)\b",
        r"\b(marna|mar jana|mar jaana|mar jaun|mar jau|mar jaoon|marne ka (mann|man|dil|irada|soch)|marne ki soch|jaan (dena|de dun|de doon|de du|lena|le lun|le loon|le lu))\b",
        r"\b(khud ko|khudko|apne aap ko|apne ko) (maar|mar|khatam|khatm|finish|end) (dun|doon|du|dalun|dalu|lun|loon|lu|dena|dalna|karna|kar dun|kar doon|kar du)\b",
        r"\b(khud ko|khudko) (maarna|marna|khatam karna) (chahta|chahti|chahte)\b",
        r"\b(sab|sb|sab kuch|sabkuch|zindagi|life|yeh zindagi) (khatam|khatm|khtm|finish|end) (kar (dun|doon|du|dena|dunga|dungi|deta|deti|dalun|dalu|lun|loon)|karna (chahta|chahti|hai))\b",
        r"\b(aatmahatya|atmahatya|atma hatya|khudkushi|khud kushi|khudkhushi)\b",
        r"\b(zindagi|life) se (chhutti|chutti|mukti|azaadi|azadi) (chahiye|chahta|chahti|le lun|lena)\b",
        r"\bsuicide kar(na|unga|ungi|ne ka|ne ki|ke)\b",
        r"(आत्महत्या|खुदकुशी|मरना चाहत|मर जाना चाहत|मर जाऊँ|मर जाऊं|जान दे द|जान ले ल|खुद को (मार|खत्म|ख़त्म)|सब खत्म कर द|सब ख़त्म कर द|ज़िंदगी खत्म|जिंदगी खत्म|ज़िन्दगी ख़त्म|अपनी जान)",
    ],
    "suicide_mention": [
        r"\b(suicide|suicidal|sucide|khudkushi|aatmahatya|atmahatya)\b",
        r"(आत्महत्या|खुदकुशी)",
    ],
    "plan": [
        r"\b(have|got|made|making) a plan\b.{0,40}\b(die|end|kill|suicide|leave|go)\b",
        r"\b(i('ve| have) (decided|planned|figured out how|worked out how|chosen)|i('m| am) going to (do it|end it|jump|hang|overdose|cut deep)|it'?s decided|decided (to|that i)('ll)? (die|end|kill|leave|go))\b",
        r"\b(wrote|written|writing|typed) (a |my )?(suicide |goodbye |final |last )?(note|letter|will)\b",
        r"\b(giving away|gave away) my (things|stuff|belongings)\b",
        r"\b(soch liya|soch li|faisla kar liya|decide kar liya|tay kar liya|plan bana liya|plan hai|plan ready|plan kar liya|kar hi dunga|kar hi dungi)\b",
        r"(सोच लिया|फैसला कर लिया|फ़ैसला कर लिया|तय कर लिया|प्लान बना|कर ही दूंगा|कर ही दूंगी)",
    ],
    "means": [
        r"\b(have|got|bought|collected|saved|saving|hiding|hid|keeping|stolen|stole|took out|holding|found) (the |a |some |my |enough |lots of |\d+ )?(pills|tablets|sleeping (pills|tablets)|paracetamol|dolo|crocin|rope|blade|razor|knife|gun|pistol|revolver|poison|rat poison|pesticide|phenyl|acid|kerosene|sulphas|celphos|insulin)\b",
        r"\b(rope|blade|razor|knife|gun|pistol|poison|rat poison|pesticide|phenyl|sulphas|celphos|sleeping pills|pills) (is|are) (ready|with me|in my (hand|bag|room|pocket)|next to me|beside me|here)\b",
        r"\b(in my hand|next to me|beside me|in front of me) (right now|now)?\b.{0,40}\b(pills|tablets|rope|blade|razor|knife|gun|poison|phenyl)\b",
        r"\b(pills|tablets|rope|blade|razor|knife|gun|poison|phenyl|pesticide|sulphas) .{0,20}(in my hand|next to me|beside me|in front of me|with me)\b",
        r"\b(goliyan|goliya|goli|rassi|dupatta|blade|chaku|chhuri|zeher|zehar|jahar|sulphas|phenyl|dawai|dawaiyan|keede marne ki dawa|chuhe marne ki dawa) .{0,25}(rakhi|rakha|rakh li|rakh liye|jama|kharid|khareed|le aaya|le aayi|le li|le liye|pass hai|paas hai|mere paas|haath me|hath me|haath mein|hath mein|taiyar|ready)\b",
        r"\b(mere paas|paas me|paas mein|haath me|haath mein|hath me) .{0,20}(goliyan|goliya|goli|rassi|blade|chaku|chhuri|zeher|zehar|sulphas|phenyl|pistol|bandook|dawaiyan)\b",
        r"\b(chhat|chat|terrace|roof|bridge|pul|railway|train|track|patri|fan|pankha|ceiling fan|building) .{0,30}(ja raha|ja rahi|jaa raha|jaa rahi|jaunga|jaungi|khada|khadi|baitha|baithi|pe hoon|par hoon|pe hu|par hu|se kood|se jump)\b",
        r"(गोलियाँ|गोलियां|रस्सी|दुपट्टा|ब्लेड|चाकू|ज़हर|जहर|फिनाइल|सल्फास).{0,20}(रख|जमा|खरीद|ले (ली|लिया|आया|आई)|पास|हाथ में|तैयार)",
    ],
    "intent": [
        r"\b(i('m| am) (going to|gonna|about to) (do it|do this|end (it|this|my life)|kill myself|die|take them( all)?|take (the|all the|these|those|all of the) (pills|tablets|goliyan)|take all of (them|it)|swallow (them|it|the pills)|jump|hang myself|cut deep|use (it|them|the rope|the blade)))\b",
        r"\b(i will|i'?ll) (do it|end (it|this|my life)|kill myself|be dead|be gone|take them all|jump|hang myself)\b",
        r"\b(this is (goodbye|the end|my last message)|goodbye everyone|no one can stop me|nothing can stop me|i('ve| have) made up my mind|my mind is made up|can'?t stop myself)\b",
        r"\b(main|mai|mein) (aaj|abhi|ab|aaj raat|kal)? ?(kar (raha|rahi) hoon|karne (ja raha|ja rahi|wala|wali) hoon|kar (dunga|dungi|lunga|lungi))\b.{0,30}\b(khatam|end|suicide|marne|mar)",
        r"\b(ab|aaj|abhi) (main|mai|mein) (mar|marne|khatam|khatm|jaan) .{0,20}(raha|rahi|wala|wali|dunga|dungi|lunga|lungi)\b",
        r"\b(mujhe koi nahi rok sakta|koi rok nahi sakta|bas ab (bahut|bohot|bohut) (hua|ho gaya)|alvida|last message|aakhri message|aakhri baar)\b",
        r"(अलविदा|आखिरी (संदेश|मैसेज|बार)|कोई नहीं रोक सकता|मन बना लिया|आज (मैं )?(मर|खत्म))",
        r"\b(dawa|dawai|dawaiyan|goliyan|goliya|goli|zeher|zehar|jahar|phenyl|acid|sulphas|poison|pills|tablets|keede marne ki dawa|chuhe marne ki dawa) .{0,50}(pee|pi|kha|khaa|nigal) (lun|loon|lu|lunga|lungi|leta hoon|leti hoon|leta hu|leti hu|jaun|jaaun)\b",
        r"\b(soch (raha|rahi) (hoon|hu|hun) (ki )?)(sab |sb |ab )?(pee|pi|kha|khaa|nigal|khatam kar|khatm kar|kood|jump|fanda laga|phanda laga) (lun|loon|lu|lunga|lungi|dun|doon|du|jaun|jaaun)\b",
        r"\bi will do what (they|the voices|it) (say|says|tell me|want)\b",
    ],
    "timeframe": [   # only counted when some ideation category is present
        r"\b(tonight|today|right now|rn|now|this (evening|morning|night|afternoon)|in (a few|an|\d+) (hours?|minutes?)|before (morning|dawn|sunrise|anyone wakes)|after (everyone|they) (sleep|sleeps|leave|leaves)|by (tomorrow|morning|tonight|midnight)|at midnight|this weekend|on my birthday|when (they|everyone) (leave|leaves|go|goes) out)\b",
        r"\b(aaj|abhi|aaj raat|aaj rat|raat ko|aaj hi|kal subah se pehle|subah se pehle|jab sab so jayenge|jab sab so jaenge|ghar wale (bahar|chale) jayenge|kal tak|is weekend|birthday pe|birthday par)\b",
        r"(आज रात|आज ही|अभी|रात को|सुबह से पहले|जब सब सो जाएंगे|कल तक)",
    ],
    "in_progress": [
        r"\b(i('ve| have)? ?(just )?(took|taken|swallowed|had|ate|drank|drunk|consumed|popped)) (all |the |some |a lot of |a bottle of |half a bottle of |half the |\d+ |many |too many |whole strip of |a strip of |the whole )?(pills|tablets|sleeping pills|paracetamol|dolo|crocin|medicines|meds|bottle|strip|phenyl|poison|rat poison|pesticide|acid|kerosene|sulphas|bleach|insulin|whatever i could find)\b",
        r"\b(i('ve| have) just (cut|slit|slashed)|just (cut|slit|slashed) (myself|my (wrist|wrists|arm|arms|thigh|thighs|neck))|i('m| am) (cutting|slitting) (myself|my (wrist|wrists|arm|arms)) (right now|now)|(cut|slit|slashed) (myself|my (wrist|wrists|arm|arms|neck)) (just now|right now|a minute ago|and (it'?s|its|i'?m|im) bleeding)|bleeding (a lot|heavily|and (it )?won'?t stop|won'?t stop))\b",
        r"\b(i('m| am) (on|at|standing on|sitting on|standing at|at the edge of) (the |a )?(roof|rooftop|terrace|bridge|ledge|edge|railway track|tracks|platform edge|balcony edge|window ledge|\d+th floor))\b",
        r"\b(rope|noose|dupatta|belt|wire) (is )?(around|round) my neck\b",
        r"\b(tied|tying) (the |a )?(rope|noose|dupatta|saree|belt)\b",
        r"\b(doing it now|i('m| am) doing it|started (doing it|cutting)|it'?s done|i did it|just did it|already (took|taken|done it|cut))\b",
        r"\b(maine|mene|mai ne|main ne) .{0,30}(kha li|kha liya|kha liye|kha lee|pee li|pi li|pee liya|pi liya|nigal li|nigal liya|le li hain|le liya hai)\b",
        r"\b(goliyan|goliya|goli|dawai|dawaiyan|zeher|zehar|phenyl|sulphas|acid|poison|puri strip|poori strip|saari goliyan|sari goliyan|saari dawaiyan|sari dawaiyan) (ek saath |ek sath |ikatthi |ikathi |ek baar me |sab |saari |sari |abhi )?(kha li|kha liya|kha liye|kha lee|pee li|pi li|pee liya|pi liya|nigal li|le li)\b",
        r"\b(haath|hath|kalai|kalaai) (kaat|kat) (liya|li|diya|di)\b",
        r"\b(chhat|chat|terrace|bridge|pul|patri|track|balcony) (pe|par|pr) (khada|khadi|baitha|baithi|hoon|hu|hun)\b",
        r"\b(gale me|gale mein|gale pe|gardan me|gardan mein) (rassi|dupatta|belt|fanda|phanda)\b",
        r"\b(fanda|phanda) (laga|bana|tayar|taiyar)\b",
        r"(खा ली|खा लिया|खा लिए|पी ली|पी लिया|निगल ली|हाथ काट लिया|कलाई काट|छत पर (खड़ा|खड़ी|बैठा|बैठी)|पुल पर (खड़ा|खड़ी)|गले में (रस्सी|दुपट्टा|फंदा)|फंदा (लगा|बना))",
    ],
    "self_harm_nssi": [
        r"\b(cut|cutting|cuts|burn|burning|burnt|scratch(ed|ing)? till|hit|hitting|punch|punching|bang(ed|ing)?) (myself|my (arm|arms|wrist|wrists|thigh|thighs|skin|head|face|body)|my head against)\b",
        r"\b(self[- ]?harm(ed|ing)?|hurt(ing)? myself|hurting myself|harm(ing)? myself|relapsed and cut|blade (again|marks)|fresh cuts|razor (on|to) my)\b",
        r"\b(khud ko|khudko|apne ko|apne aap ko) (kaat|kat|jala|jalaa|maar|mar|nuksan|chot|hurt|takleef|dard) (liya|li|leti|leta|deti|deta|pahunchata|pahunchati|karta|karti|diya|di)\b",
        r"\b(blade se|cutter se|chaku se|aag se|lighter se|sigarette se|cigarette se) .{0,20}(haath|hath|kalai|kalaai|khud|apne|jang|skin)\b",
        r"\b(haath|hath|kalai|kalaai|jaang|jang) (pe|par|me|mein) (cut|cuts|kaat|katne|blade|nishaan)\b",
        r"(खुद को (काट|जला|चोट|नुकसान)|हाथ (काट|जला)|कलाई (काट|पर कट)|ब्लेड से)",
    ],
    # ---- others -----------------------------------------------------------------------------
    "harm_to_others": [
        r"\b(telling|tell|told|ordering|order|commanding|command|asking|ask|pushing|urging) me to (kill|murder|stab|shoot|strangle|poison|hurt|harm|beat|attack|burn) (him|her|them|someone|people|my \w+( \w+)?|the \w+)\b",
        r"\b(thoughts|urges|images|impulses|feel like|feeling like|scared i('ll| will|might)|afraid i('ll| will|might)) (of )?(hurting|killing|harming|dropping|smothering|drowning|shaking|throwing|hitting) (the|my|our) (baby|child|children|kids|son|daughter|infant|newborn)\b",
        r"\b(bachche|bacche|bache|baby|bete|beti) ko (maarne|marne|nuksan|chot|girane|fenkne|dabane) (ka|ke) (khayal|khyal|vichaar|vichar|thoughts|urge|mann|man|dil) (aata|aate|aa raha|aa rahe|hota|karta)\b",
        r"\b(want to|wanna|going to|gonna|will|could|feel like|about to|planning to|thinking of|ready to) (kill|murder|stab|shoot|strangle|poison|hurt|beat up|smash|burn|attack|finish off|end) (him|her|them|my (wife|husband|mother|father|mom|dad|brother|sister|son|daughter|boss|boyfriend|girlfriend|in[- ]laws|mother[- ]in[- ]law|neighbour|neighbor|roommate|baby|child|kids)|someone|everyone|people|that (man|woman|guy|boy|girl)|the (baby|kids|children))\b",
        r"\b(i('ll| will|'m going to| am going to) (kill|murder|hurt|stab|shoot) (him|her|them|someone|my \w+)|kill (him|her|them) (tonight|today|myself)|hurt (the|my) (baby|child|kids))\b",
        r"\b(usko|use|unko|unhe|isko|ise|sabko|sab ko|apni biwi ko|apne pati ko|bachche ko|bache ko|bacche ko|saas ko|boss ko|is aadmi ko|us aadmi ko|us aurat ko) (maar|mar|khatam|khatm|jaan se|chaku|goli) (dunga|dungi|dalunga|dalungi|dena|dalna|kar dunga|kar dungi|maar dunga|maar dungi|chahta|chahti|ka mann|ka man|ka dil)\b",
        r"\b(maar dunga|maar dungi|mar dunga|mar dungi|jaan se maar|khatam kar dunga|khatam kar dungi|khoon kar dunga|khoon kar dungi|chaku maar|goli maar) (usko|use|unko|unhe|isko|sabko|sab ko|uski|usse)?\b",
        r"(उसको (मार|खत्म|ख़त्म)|उसे मार|जान से मार|मार (दूंगा|दूँगा|दूंगी|दूँगी)|खत्म कर (दूंगा|दूंगी)|सबको मार)",
    ],
    "abuse_victim": [
        r"\b(he|she|they|my (husband|wife|father|dad|mother|mom|brother|uncle|boyfriend|partner|in[- ]laws|mother[- ]in[- ]law|father[- ]in[- ]law|saas|sasur|boss|teacher|cousin|stepfather|step ?dad)) (hits?|hit|beats?|beat|slaps?|slapped|kicks?|kicked|punches|punched|chokes?|choked|strangled|burn(s|ed|t)|threatens? to kill|threatened to kill|locks? me|locked me|forces? me|forced me|rapes?|raped|molests?|molested|touches me|touched me|abuses?|abused|hurts|hurt) (me|us|my (kids|children|mother|mom))\b",
        r"\b(beats? me( up)?|hits me|slaps me|kicks me|chokes me|threatens to kill me|threatened to kill me|forces? me to|forced me to|raped|rape me|molest(ed|s)? me|touch(es|ed)? me (inappropriately|there|down there|without|at night)|sexually (abused|assaulted|harassed)|marital rape|domestic violence|dowry (harassment|demand|torture)|burn(ed|t) me|locked me (in|up)|won'?t let me (leave the house|leave|call anyone|talk to anyone|see anyone|see my (family|friends|parents)))\b",
        r"\b(gets? violent|is violent|was violent|hit me again|hit me last night|hit me today|beat me (again|yesterday|last night|today)|black eye|bruises? (from|he gave)|afraid (he|she) will (kill|hurt) me|scared (he|she)('ll| will) (kill|hurt) me)\b",
        r"\b(marta hai|maarta hai|maarte hain|marte hain|peetta hai|pitta hai|peetata hai|pitai karta|pitai karte|pitti hai|haath uthata|hath uthata|haath uthaya|hath uthaya|thappad (marta|maarta|mara|maara)|jaan se maarne ki dhamki|dhamki deta|dhamki dete|zabardasti|jabardasti|galat tareeke se (chhuta|chuta|touch)|chhed(ta|te) hai|chedta hai|sasural wale (pareshan|tang|torture|maarte|marte)|dahej (ke liye|maang)|gharelu hinsa|band kar (deta|dete|diya) hai|bahar nahi jaane dete|phone nahi (dete|chalane dete))\b",
        r"(मारता है|मारते हैं|पीटता है|पीटते हैं|हाथ उठाता|थप्पड़ मार|जान से मारने की धमकी|ज़बरदस्ती|जबरदस्ती|गलत तरीके से (छूता|छुआ)|छेड़ता|दहेज|घरेलू हिंसा|बलात्कार|बंद कर (देता|दिया))",
    ],
    "psychosis": [
        r"\b(hear(ing)? voices|voices? (tell|tells|telling|told|say|says|saying|keep|keeps|command|commanding|ordered|order) (me|us)|the voices|a voice (tells|told|says|keeps))\b",
        r"\b((they|people|the government|the police|my neighbours?|my neighbors?|agencies|aliens|someone) (are|is|'re|'s) (watching|spying on|following|tracking|monitoring|recording|poisoning|controlling|reading) (me|my (mind|thoughts|phone)))\b",
        r"\b(camera|cameras|chip|microchip|transmitter|device|tracker) (in|inside|implanted in|planted in) (my|the) (head|brain|body|teeth|tooth|wall|walls|room|tv|phone|ac|fan)\b",
        r"\b(control(s|ling)? my (thoughts|mind|body)|thoughts are not mine|thoughts (are being|being) (read|broadcast|stolen|inserted)|put(ting)? thoughts in my head|reading my mind|they can hear my thoughts)\b",
        r"\b(i('m| am) (god|the chosen one|a prophet|the messiah|chosen by god|on a (special|secret|divine) mission|being tested by god|the reincarnation of)|god (speaks to me directly|has chosen me|gave me a mission)|special (mission|powers)|secret messages? (from|in|through) (the )?(tv|news|radio|songs|numbers|ads)|the tv (talks|speaks) to me|signs (meant )?(only )?for me)\b",
        r"\b(awaaz|awaazein|awaazen|aawaz|aawazein|awaz|awazein) (aati|aate|sunai|sunayi|bolti|kehti|kahti|batati) (hai|hain|deti|dete|rehti|rehte)\b",
        r"\b(mera peecha|mera picha|meri jasoosi|mujhpe nazar|mujh pe nazar|mujh par nazar|meri nigrani|mujhe track|mujhe follow) (kar|ho|rakh|kiya|karte|karta|rahe|rahi)\b",
        r"\b(mere dimaag me|mere dimag me|mere sar me|mere sir me|mere daant me|mere daant mein) (chip|camera|machine|device|transmitter)\b",
        r"\b(mere (vichaar|vichar|thoughts|khayal) (control|padh|padhe|chori|sun))\b",
        r"\b(bhagwan|god|allah|khuda|ishwar|devi|mata) (ne )?(mujhe|mujhse) (chuna|chun liya|mission|kaam|aadesh|seedha|direct) .{0,20}(diya|hai|baat|bolte|bolta|bolti)\b",
        r"(आवाज़ें (आती|सुनाई|बोलती|कहती)|आवाजें (आती|सुनाई)|मेरा पीछा कर|मुझ पर नज़र|मेरे दिमाग में (चिप|कैमरा)|मेरे विचार (पढ़|कंट्रोल)|भगवान ने मुझे (चुना|मिशन)|टीवी मुझसे बात)",
    ],
    "eating_disorder_purge": [
        r"\b((make|made|making|force|forced|forcing) myself (throw up|vomit|puke|sick)|throw(ing)? up (after|everything) (i )?(eat|ate|eating|meals?)|purg(e|ed|ing)|binge(d|ing)? and (purge|throw up|vomit)|(take|took|taking|use|using|abuse|abusing) laxatives (to|for|every|daily|after)|chew and spit|haven'?t eaten (in|for) (\d+|three|four|five|six|seven|two) days|not eaten (in|for) (\d+|three|four|five|two) days|starv(e|ing) myself|fasting to (lose|punish|get thin)|only (water|black coffee) for (\d+|three|four|five) days|calories? .{0,20}(too fat|disgusting|punish)|scared of (eating|food) because)\b",
        r"\b(khane ke baad|khana kha ke|kha ke) (ulti|ultiyan|vomit|vomiting) (kar|karti|karta|karne|hoti|aati|karwa)\b",
        r"\b(ulti kar (deti|deta|leti|leta) hoon|ungli daal ke ulti|jaan ke ulti|zabardasti ulti|khud ulti|(\d+|teen|char|paanch|do) din se (kuch )?(nahi|nhi) khaya|khana (band|chhod|chod) diya (hai|hu|hoon)|bhookha rehti|bhookhi rehti|bhukha rehta|khud ko bhookha|moti (hoon|hu) .{0,20}(khana|khaungi|nahi))\b",
        r"(खाने के बाद उल्टी|जबरदस्ती उल्टी|ज़बरदस्ती उल्टी|उंगली डाल|दिन से (कुछ )?नहीं खाया|खाना (बंद|छोड़) दिया|खुद को भूखा)",
    ],
    "overdose_substance": [
        r"\b(overdos(e|ed|ing)|od'?d|od on|took (too many|a lot of|all the|all my|the whole (bottle|strip)|\d\d+) (pills|tablets|meds|medicines|paracetamol|dolo|sleeping pills|of my)|swallowed (a |the |half a )?(bottle|strip|handful|lot)|drank (half a |a |the |some |a cup of |a glass of |a bottle of |half the )?(bottle of )?(phenyl|acid|kerosene|poison|rat poison|bleach|harpic|dettol|sanitizer|pesticide|insecticide)|(ate|eaten|had|took|consumed|swallowed) (rat poison|poison|pesticide|sulphas|celphos|sleeping pills and alcohol))\b",
        r"\b(too many|bahut saari|bohot saari|bohut saari|saari|sari|puri strip|poori strip|\d\d+) (goliyan|goliya|goli|pills|tablets|dawai|dawaiyan|neend ki goliyan|neend ki goli) (ek saath |ek sath |ikatthi |ek baar me |abhi )?(kha|khaa|kha li|kha liya|kha liye|le li|nigal)\b",
        r"\b(phenyl|zeher|zehar|jahar|harpic|acid|kerosene|mitti ka tel|dettol|sulphas|celphos|keede ki dawa|keede marne ki dawa|chuhe ki dawa|chuhe marne ki dawa|dawa) (pee|pi|pee li|pi li|pee liya|pi liya|kha li|kha liya|nigal li|nigal liya)\b",
        r"\b(nashe me|nashe mein|drunk and) .{0,30}(goliyan|pills|khatam|end|mar)\b",
        r"(ज़हर (खा|पी)|जहर (खा|पी)|फिनाइल पी|सल्फास|बहुत सारी गोलियाँ|बहुत सारी गोलियां|पूरी स्ट्रिप|नींद की गोलियाँ खा|नींद की गोलियां खा|ओवरडोज़|ओवरडोज)",
    ],
    "medical_emergency": [
        r"\b(chest pain|crushing (chest|pain)|pressure in (my )?chest|heart attack|can'?t breathe|cannot breathe|can'?t catch my breath|struggling to breathe|difficulty breathing|turning blue|lips (are )?blue|unconscious|not responding|passed out and|seizure|convulsion|fits? (right now|again)|face droop|slurred speech|stroke|bleeding (a lot|heavily|won'?t stop)|blood won'?t stop|vomiting blood|coughing (up )?blood|severe allergic|throat (is )?closing|anaphyla\w*)\b",
        r"\b(seene (me|mein) dard|seene me (bhari|jalan|dabav)|saans nahi aa|saans lene (me|mein) (takleef|dikkat|problem|pareshani)|dil ka daura|behosh|behosh ho|daura (aa|pad)|jhatke aa|khoon (nahi|nhi) ruk|bahut khoon|khoon ki ulti|khoon ki ulti aa)\b",
        r"(सीने में दर्द|सांस नहीं आ|साँस नहीं आ|सांस लेने में|दिल का दौरा|बेहोश|दौरा (आ|पड़)|झटके|खून नहीं रुक|बहुत खून|खून की उल्टी)",
    ],
    "minor_indicator": [
        r"\b(i('m| am)|i am only|im|main|mai|mein|meri age|my age is|age is|aged?|turning|just turned|abhi) (only |just |sirf )?(1[0-7]|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen)( years? old| yrs? old| yo| saal( ka| ki)?| years?| ki (hoon|hu)| ka (hoon|hu))?\b(?! ?(months?|weeks?|days?|years? (ago|back|married|of)|kg|km|%|percent|lakh|thousand|rupees|rs|marks|th floor|minutes))",
        r"\b(1[0-7]|thirteen|fourteen|fifteen|sixteen|seventeen) (years? old|yrs? old|yr old|year old|saal (ka|ki) (hoon|hu|hun)|saal ki hoon|saal ka hoon)\b",
        r"\b(in|from|of|padhta|padhti|study(ing)? in|student of) ?(class|std|standard|grade) ?(6|7|8|9|10|11|12|vi|vii|viii|ix|x|xi|xii|6th|7th|8th|9th|10th|11th|12th)\b",
        r"\b(6th|7th|8th|9th|10th|11th|12th|tenth|ninth|eighth|seventh|eleventh|twelfth) (class|std|standard|grade|board|boards|grader)\b",
        r"\b(class|kaksha) (6|7|8|9|10|11|12|chhe|saat|aath|nau|das|gyarah|barah) (me|mein|ka|ki|hoon|hu)\b",
        r"\b(my (mom|mum|mummy|mama|dad|papa|parents) (won'?t|wont|don'?t|dont) let me|my parents (grounded me|took my phone|will beat me if|check my phone)|after school|school (ke baad|se aake|me sab|mein sab)|my class teacher|my school counsellor|my school counselor|homework|tuition (teacher )?(ke baad|se aake)|my principal|hostel warden said)\b",
        r"(मैं (1[0-7]) (साल|वर्ष)|(1[0-7]) साल (का|की) हूँ|(1[0-7]) साल (का|की) हूं|कक्षा (6|7|8|9|10|11|12)|दसवीं|नौवीं|आठवीं|बारहवीं|ग्यारहवीं|स्कूल के बाद|मम्मी (नहीं )?(जाने|करने) नहीं देत|पापा मारेंगे)",
    ],
    "method_request": [
        r"\b(how (many|much)|what (dose|dosage|amount|quantity)|kitni|kitna|kitne) .{0,40}(pills|tablets|paracetamol|dolo|crocin|sleeping pills|mg|grams?|ml|goliyan|goliya|goli|dawai|phenyl|zeher|poison|sleeping tablets|insulin|alcohol)\b.{0,60}\b(die|death|dead|kill|lethal|fatal|overdose|od|enough|too many|dangerous|deadly|not wake|never wake|sleep forever|marne|mar jaye|mar jaun|mar jaaun|mar sakta|mar sakte|mar sakti|maut|khatam|jaan)\b",
        r"\b(die|death|dead|kill|lethal|fatal|overdose|marne|maut|khatam) .{0,40}\b(how (many|much)|what (dose|dosage|amount|quantity)|kitni|kitna|kitne) .{0,30}(pills|tablets|paracetamol|dolo|sleeping pills|mg|goliyan|goliya|goli|dawai)\b",
        r"\b(lethal|fatal|deadly|toxic|overdose|od) (dose|dosage|amount|quantity|level|limit)\b",
        r"\b(is|are|does|would|will|can) (\d+|a (bottle|strip|handful|box) of|too many|that many|this many|two strips of|\w+ strips? of) .{0,30}(pills|tablets|paracetamol|dolo|crocin|sleeping pills|mg|goliyan|phenyl|insulin) .{0,20}(enough|kill|fatal|lethal|deadly|dangerous|die)\b",
        r"\b(painless|pain[- ]?free|least painful|most painful|quickest|fastest|quick|easiest|easy|best|most (effective|reliable|certain|peaceful)|peaceful|cleanest|surest|sure[- ]shot|guaranteed|cheapest|simplest) (way|ways|method|methods|means|tareeka|tarika|tareeke|tarike|option) (to|of|for) (die|dying|death|kill (myself|yourself|oneself|someone|a person)|end (it|it all|my life|a life|your life|one'?s life)|suicide|go|leave|not wake up|ending (it|a life|my life)|killing (myself|yourself|oneself)|exit|check out|take (my|your|one'?s|their) (own )?life|self[- ]harm|od|overdose)\b",
        r"\b(how (do|can|could|would|should) (i|you|one|someone|a person|people|a character|my character|she|he|they)|how to|ways? to|methods? (to|of|for)|tips? (to|for|on)|steps? (to|for)|instructions? (to|for|on)|guide (to|for|on)|best way to|what'?s the (best|right|proper) way to|tell me how to|teach me (how )?to|explain how to|describe how to) (kill (myself|yourself|oneself|himself|herself|themselves|someone|a person|a man|a woman|a character)|end (it|it all|my life|your life|one'?s life|their life|a life|her life|his life)|take (my|your|one'?s|their|her|his) (own )?life|commit suicide|die (painlessly|quickly|peacefully|without pain|fast|at home|in (my )?sleep|quietly|easily)|hang (myself|yourself|oneself|himself|herself|a person|someone)|tie a noose|make a noose|slit (my|your|one'?s|her|his) wrists?|cut (my|your|one'?s|the) wrists? (so|to|deep|properly|correctly|right|the right way)|overdose( on| with| safely| properly| successfully)?|od|suffocate (myself|yourself|oneself)|poison (myself|yourself|oneself|someone|a person)|drown (myself|yourself|oneself)|jump (from|off) (a|the|which)|not feel pain (when|while) dying|bleed out|stop (my|your|the) heart|get (a gun|poison|sleeping pills|pills|cyanide|sulphas|rat poison) (without|easily|online|fast|quickly|in india))\b",
        r"\b(which|what|whats|what'?s) (pills|tablets|medicine|medicines|meds|drug|drugs|poison|poisons|chemical|chemicals|household (items?|things|chemicals)|method|methods|way|ways|height|floor|bridge|building|place|places|rope|knot|spot|artery|vein|position|combination|combo|cocktail|mix) .{0,45}(kill|die|dying|death|dead|lethal(ity)?|fatal(ity)?|deadly|most (lethal|dangerous|effective|painless)|works? (best|fastest|quickest)|would work|guaranteed|painless|quick|surely|definitely|for sure|suicide|end it|marne|maut|jaan|khatam|mar jaye|mar jaun|mar jaaun|mar sakta|mar sakte|mar sakti|mar sakoon|instantly|on impact|without fail|fast(est)?|quick(est)?)\b",
        r"\b(does|do|will|would|can|could|is|are) (\w+ ){0,3}(paracetamol|dolo|crocin|sleeping pills|phenyl|harpic|rat poison|bleach|dettol|insulin|cough syrup|benadryl|whisky|alcohol|antidepressants|antidepressant|my (meds|medicines|medication|pills|tablets)|these pills|this|that|it|hanging|jumping|drowning|cutting|a fall from \w+|helium|carbon monoxide|exhaust fumes|charcoal|sleeping pills with alcohol) .{0,25}(kill (you|me|a person|someone|him|her)|be (enough|fatal|lethal|painless|painful|quick)|(enough|lethal|fatal|deadly|painless|painful|quick|fast|reliable|certain) (to|for) (die|kill|death|end)|work|hurt (a lot|much)|cause death|lead to death|end (it|life))\b",
        r"\b(does it hurt|how (much )?(does|would|will) it hurt|how long (does|would|will) it take|how long until|is it painful|is it quick|is it painless|what (does|would) it feel like|would i feel (anything|pain)|do you (feel|suffer)) .{0,30}(to )?(die|dying|death|dead|hang(ing)?|overdos(e|ing)|drown(ing)?|jump(ing)?|cut(ting)?|bleed(ing)?( out)?|poison(ing)?|suffocat(e|ing|ion)|slit|wrist|rope|pills|fall|from (a|the) (roof|bridge|building|\d+th floor)|carbon monoxide|starv(e|ing|ation))\b",
        r"\b(how (long|much) (does|would|will|do|should) (it take|you need|one need|a person need|i need|someone need) (to|before) (die|death|lose consciousness|pass out|bleed out|stop breathing|be dead|be gone)|(time|minutes|hours) (to die|until death|before death|to bleed out|does death take)|how (deep|far|high|hard|tight|much) (do (i|you) (have to|need to)|should (i|you)|does (it|one|a person) (have|need) to|must (i|you|one)|is enough to) (cut|go|jump|fall|press|pull|tie|slice|squeeze|bleed|take|swallow|drink|drop|be)( to (die|bleed|hit|kill|pass)| for (it|death|an artery))?)\b",
        r"\b(where|which|what) (artery|arteries|vein|veins|spot|spots|place on the (wrist|arm|neck|body)|part of the (wrist|arm|neck|body)|point|pulse|point on the neck) .{0,30}(cut|slit|slice|press|hit|bleed|quick|fast|lethal|fatal|die|death|kill|most blood|fastest|sever)\b",
        r"\b(how (high|tall|many floors?|many storeys|many stories)|what height|minimum height|which floor|what floor|how many floors? up|is the (\d+|second|third|fourth|fifth|sixth|seventh|tenth|first) floor|is \d+ (floors?|metres?|meters|feet|ft|storeys|stories)|would \d+ (floors?|metres?|meters|feet|ft)|from (how|what) (high|height)) .{0,45}(die|death|dead|kill|fatal|lethal|enough|survive|sure|certain|instant|instantly|jump|fall|definitely|guaranteed|not survive|on impact|mar|maut|jaan)\b",
        r"\b(where (can|do|could|would|should) (i|you|one|someone|a person|a character) (buy|get|find|order|procure|obtain|source|purchase|acquire)|how (to|do (i|you|people)|can (i|you|one|someone)) (buy|get|find|order|procure|obtain|source|purchase|acquire|get hold of|get (my|your) hands on)|is it (easy|possible|legal) to (buy|get|order)|can (i|you|one|someone) (buy|get|order)) .{0,20}(a gun|a pistol|a revolver|pistol|gun|guns|poison|poisons|rat poison|cyanide|potassium cyanide|sulphas|celphos|aluminium phosphide|sleeping pills|sleeping tablets|barbiturates|nembutal|pentobarbital|insulin|fentanyl|morphine|opioids|chloroform|helium( tank| cylinder)?|nitrogen( tank| cylinder)?|exit bag|exit kit|a rope strong enough|a sturdy rope|strong rope|carbon monoxide|pesticide|insecticide|arsenic|thallium|antifreeze|lethal (pills|drugs|medicine)|something (lethal|deadly|to end it|to die|that would kill)|the (pills|poison|gun|rope|drug|means) (to|for|that would))\b",
        r"\b(is|are|does|do|would|will|can|could|how) (hanging|jumping|drowning|cutting|overdosing|overdose|poisoning|suffocation|suffocating|carbon monoxide|helium|nitrogen|exhaust fumes|starvation|starving|freezing|electrocution|sleeping pills|an overdose|od|a fall|falling|a gun|a gunshot|shooting|a rope|a noose|wrist cutting|slitting wrists|bleeding out|a train|trains|a bridge|rat poison|sulphas|phenyl|harpic|bleach|insulin|paracetamol|dolo) .{0,30}(painless|painful|quick|fast|slow|reliable|effective|certain|lethal|fatal|deadly|peaceful|sure|guaranteed|better|worse|easier|easiest|harder|the best|work(s)? (for|at)|survivable|likely to (work|fail|kill|succeed)|fail|succeed|kill (you|me|a person|someone)|cause (death|much pain|pain)|compare|compared|versus|vs\.?|or (\w+ ){0,2}(better|worse|faster|quicker|easier|more|less)|than)\b",
        r"\b(compare|comparison|comparing|difference between|rank|ranking|list|pros and cons|which (is|one is|one'?s|would be)|what(’|')?s (better|worse|quicker|more|less)) .{0,40}(ways? (to|of) (die|dying|kill|suicide|end)|suicide methods?|methods? (of|for|to) (suicide|dying|killing|self[- ]harm|ending)|hanging|overdos(e|ing)|drowning|jumping|poisoning|pills (vs|versus|or) (hanging|jumping|rope)|rope (vs|versus|or) pills|lethality|fatal|lethal)\b",
        r"\b(which|what|whats|what'?s|how many|how much|lethal|fatal|deadly|painless|painful|quick|fast|method|methods|dose|dosage|ways? to|how to|how (do|does|would|can)) .{0,80}\b(for (my|a|the) (novel|story|book|character|protagonist|script|screenplay|film|play|poem|fanfic|fan fiction)|for (research|a research paper|my (research|paper|thesis|dissertation|project|assignment|psychology (class|project|paper)|science (project|fair)|essay|presentation|college project|school project|chemistry (class|project)|biology (class|project)|pharmacology (class|exam)|nursing (class|exam)|medical (school|exam)|forensic))|(asking|this is|it is|it'?s|its) (just )?(for (a friend|someone else|my friend|a cousin|a relative|a classmate|a colleague|a neighbour|my brother|my sister|a character|a story|a book|research|fiction|a novel|writing|academic|educational|informational|curiosity|general knowledge)|hypothetical(ly)?|theoretical(ly)?|curiosity|academic|out of curiosity|purely academic|just (curious|wondering|asking|hypothetical|theoretical))|hypothetically( speaking)?|theoretically( speaking)?|in theory|as a (writer|novelist|author|researcher|student|nurse|doctor|pharmacist|psychology student|medical student|journalist|screenwriter)|(i'?m|i am|im) (a )?(writer|novelist|author|researcher|writing a (book|novel|story|script|thriller|screenplay)|doing research|a (psychology|medical|nursing|pharmacy|chemistry|biology|forensic) student)|(my|the|a) (character|protagonist|hero|heroine|villain|friend|cousin|roommate|sister|brother|colleague|classmate) (wants|needs|is going|plans|decides|has decided|wants to know|asked me|is asking|would like) (to (die|kill|end|overdose|hang|jump|take)|how (many|much|to))|not (for me|about me|asking for myself|planning anything|going to do it|suicidal)[,.]? (just|but|i'?m|i am|i just|only|its|it'?s)?)\b",
        r"\b(for (my|a|the) (novel|story|book|character|protagonist|script|screenplay|film|poem|fanfic)|for (research|my (research|paper|thesis|project|assignment|essay|psychology (class|project)|school project|college project))|hypothetically|theoretically|in theory|as a (writer|novelist|author|researcher|student|nurse|doctor|pharmacist|journalist)|(i'?m|i am|im) (a )?(writer|novelist|author|researcher|writing a (book|novel|story|script|thriller))|(my|the|a) (character|protagonist|hero|heroine|villain|friend|cousin|roommate|sister|brother|colleague|classmate) (wants|needs|is going|plans|decides|has decided|asked me|is asking) (to (die|kill|end|overdose|hang|jump|take)|how)|(asking|this is|it'?s|its) (just )?for (a friend|someone else|my friend|a cousin)|not (for me|about me|asking for myself)) .{0,80}\b(which|what|whats|what'?s|how many|how much|lethal|fatal|deadly|painless|painful|quick|quickest|fast|fastest|method|methods|dose|dosage|ways? (to|of)|how to|how (do|does|would|can|long|high|deep)|realistic(ally)?|accurate(ly)?|detail|details|describe|explain|step[- ]by[- ]step|what happens when|what it (feels|is) like) .{0,60}\b(die|dying|death|dead|kill|suicide|overdos|hang|hanging|noose|jump|wrist|slit|cut|bleed|poison|pills|tablets|paracetamol|insulin|drown|suffocat|carbon monoxide|helium|lethal|fatal|od|end (it|her life|his life|their life|a life|my life|life)|take (her|his|their|my|one'?s) (own )?life|rope|sleeping pills|marne|maut|mar (jaye|jaaye|jaun|jaaun|sakta|sakte|sakti|sakoon))\b",
        r"\b(marne ka|mar jane ka|mar jaane ka|khatam karne ka|khud ko khatam karne ka|suicide ka|suicide karne ka|jaan dene ka|jaan lene ka|khudkushi ka|khudkushi karne ka|aatmahatya ka|atmahatya ka) (sabse |sab se |koi |ek |kaun sa |konsa |kya |accha |acha |asaan |aasan |painless |dard ?free |bina dard ka |bina dard wala |jaldi |fast |quick |sahi |pakka |sure )*(tareeka|tarika|tareeke|tarike|rasta|raasta|upay|way|method|tarikha|option|idea|plan)\b",
        r"\b(kaise|kese|kis tarah|kis tareeke se|kis tarike se|kaun se tareeke se|konse tareeke se|kya karu ki|kya karun ki|kya karoon ki|kya karein ki|kya khaun ki|kya khaoon ki|kya pi ?(lun|loon|lu) ki|kya khaa ?(lun|loon|lu) ki) .{0,40}(mar (jaun|jaaun|jau|jaoon|jaayein|jayein|jaye|jaaye|sakta|sakte|sakti|sakoon|saku|jaate|jata|jaata)|maut (ho|aa|mil)|jaan (chali|nikal|de|le)|khatam (ho|kar)|khatm (ho|kar)|suicide (kar|ho)|khudkushi (kar|ho)|dard (na|nahi|nhi) ho (aur|or|aur phir)? ?(mar|maut|jaan|khatam)|neend me (hi )?(mar|chala|chali|khatam)|bina dard (ke )?(mar|maut|khatam|jaan))\b",
        r"\b(kitni|kitne|kitna|kaunsi|kaun si|konsi|kon si|kaunsa|kaun sa|konsa|kon sa|kya|kis|kaise) .{0,40}(goliyan|goliya|goli|tablets?|pills?|dawai|dawaiyan|dawa|dawaai|medicine|zeher|zehar|jahar|poison|phenyl|rassi|rope|fanda|phanda|chaku|blade|kalai|nas|nabz|chhat|chat|manzil|floor|building|pul|bridge|train|track|patri|neend ki (goli|goliyan|goliya|dawai|dawa)|paracetamol|dolo|crocin|disprin|aspirin|sulphas|celphos|harpic|acid|tel|kerosene|injection|insulin) .{0,40}(marne|mar (jaun|jaaun|jau|jaoon|jaye|jaaye|jayein|sakta|sakte|sakti|sakoon|saku|jata|jaata|jaate|jaye)|maut|jaan (chali|nikal|jaye|jaaye|le|de)|khatam|khatm|pakka|pakki|kaafi|kafi|enough|lethal|fatal|dangerous|khatarnak|deadly|kaam (karega|karegi|kar jayega|ban jayega|ho jayega|hoga)|kaam (karti|karta|kare|karegi|karega)|asar (karegi|karega|hoga)|zyada (dard|takleef) (na|nahi|nhi) ho|dard (na|nahi|nhi) (ho|hoga|hogi|hota)|dard (kam|zyada) (ho|hoga|hota)|neend me|sote (hue|huye|me|mein)|uth(ne|unga|ungi)? ?(na|nahi|nhi) (paun|paaun|paoon|sakun|sakoon)|wapas (na|nahi|nhi) (aau|aaun|aaun|aoon|uthu|uthun|uthoon)|turant|jaldi|fatafat|ek (hi )?baar me)\b",
        r"\b(kitni|kitne|kitna) (goliyan|goliya|goli|tablets?|pills?|dawai|dawaiyan|paracetamol|dolo|crocin|neend ki goliyan|neend ki goli|mg|ml|zeher|phenyl) (se|me|mein|lene se|khane se|kha ke|khake|kha kar|peene se|pi ke|pike|ek saath|ek sath|at a time|at once|together) .{0,30}(mar|maut|jaan|khatam|khatm|insaan|aadmi|koi|ek|banda|bandi|ladka|ladki|aurat|mahila|log|pakka|pakki|kaafi|kafi|enough)\b",
        r"(मरने का (सबसे |कोई |आसान |दर्द ?रहित |बिना दर्द |जल्दी |सही |पक्का )*(तरीका|तरीक़ा|रास्ता|उपाय)|कैसे (मरूं|मरूँ|मरु|मर जाऊं|मर जाऊँ|मर सकता|मर सकती|मर सकते|जान दूं|जान दूँ|जान दू|खुद को खत्म करू|खत्म करूं|खत्म करूँ|आत्महत्या करूं|आत्महत्या करूँ|आत्महत्या करें|खुदकुशी करूं|खुदकुशी करूँ)|कितनी (गोलियाँ|गोलियां|गोली|दवाई|दवा|मात्रा|ज़हर|जहर) .{0,25}(मर|मौत|जान|खत्म|ख़त्म|काफ़ी|काफी|पक्का|असर|काम)|कौन (सी|सा) (गोली|गोलियाँ|गोलियां|दवाई|दवा|ज़हर|जहर|तरीका|रस्सी|मंज़िल|मंजिल|फ़्लोर|फ्लोर) .{0,25}(मर|मौत|जान|खत्म|ख़त्म|पक्का|असर|काम|दर्द)|(फाँसी|फांसी|फंदा|फंदे) (कैसे|किस तरह|लगाने का तरीका|बनाने का|बनाने का तरीका|लगाएं|लगाऊं|लगाऊँ|बनाऊं|बनाऊँ|लगाने के लिए)|कलाई (कैसे|किस तरह|कितनी गहरी|कहाँ|कहां) (काटू|काटूं|काटूँ|काटें|काटे|काटनी|काटनी चाहिए)|नस कैसे काट|कितनी (ऊँचाई|ऊंचाई|मंज़िल|मंजिल) से (कूद|गिर)|(कूदने|गिरने) से .{0,20}(मर|मौत|पक्का|जान)|(ज़हर|जहर|गोलियाँ|गोलियां|सल्फास|फिनाइल) .{0,20}(कहाँ|कहां) (मिलेगा|मिलेगी|मिलेंगी|से मिले|से लूं|से लाऊं)|सोते (हुए|में) .{0,20}(मर|मौत|जान))",
    ],
}

_COMPILED: dict[str, list[re.Pattern]] = {cat: [re.compile(p, re.IGNORECASE) for p in pats] for cat, pats in _P.items()}

_IMMINENT_ALONE = {"in_progress", "overdose_substance", "medical_emergency", "method_request"}
_ELEVATED_ALONE = {
    "suicidal_ideation_passive", "suicidal_ideation_active", "hopelessness", "self_harm_nssi", "harm_to_others",
    "abuse_victim", "psychosis", "eating_disorder_purge", "attempt_history", "plan", "means", "intent", "suicide_mention",
}
_IDEATION = {"suicidal_ideation_passive", "suicidal_ideation_active", "hopelessness", "self_harm_nssi", "attempt_history"}
_ESCALATORS = {"plan", "means", "intent", "timeframe"}

# Common false-positive contexts for English idioms ("this exam is killing me", "dying to see you", "dead tired").
# Only used to IGNORE a match from the *active ideation* idiom patterns; everything else stands.
_IDIOM_OK = re.compile(
    r"\b(dying to (see|meet|try|know|watch|eat|go|hear|tell)|dead (tired|serious|broke|end|line|set|on|beat)|"
    r"(killing|killed) (it|me|time)|kill for (a|an|some)|to die for|drop[- ]dead|die[- ]hard|suicide squad|"
    r"suicide (prevention|awareness)( awareness| prevention)? (day|week|month|programme|program|training|poster|campaign|session|workshop|talk|seminar|webinar)|"
    r"die laughing|died laughing|i could die (of embarrassment|laughing)|killer (headache|deadline|workout|look))\b",
    re.IGNORECASE,
)
_ATTEMPT_HISTORY = re.compile(
    r"\b((tried|attempted) (to )?(kill myself|end my life|suicide|die|od|overdose)|suicide attempt|last (attempt|time i tried)|"
    r"(pehle|pichle saal|pichhle saal|last year|do saal pehle|ek baar) .{0,30}(try kiya|koshish ki|attempt kiya|goliyan kha(yi|i) thi|kaat liya tha)|"
    r"(try kiya tha|koshish ki thi|attempt kiya tha) .{0,20}(marne|suicide|khatam|jaan)|"
    r"(was|got) (hospitalised|hospitalized|admitted) after (i|the) (took|cut|overdos)|"
    r"आत्महत्या की कोशिश|मरने की कोशिश)\b",
    re.IGNORECASE,
)


_FRAMING = re.compile(r"\b(hypothetically|hypothetical|theoretically|in theory|purely academic|academic(ally)? (question|curiosity|interest)|out of curiosity|just curious|asking for a friend|for a friend|for my friend|for someone else|not for me|not about me|for (a|my|the) (novel|story|book|character|protagonist|script|screenplay|film|poem|fanfic|thriller|research|paper|thesis|project|assignment|essay|class|presentation)|(i'?m|i am|im) (a |an )?(writer|novelist|author|researcher|journalist|(psychology|medical|nursing|pharmacy|chemistry|forensic) student)|writing a (novel|story|book|script|thriller|screenplay|poem|scene)|my (character|protagonist|hero|heroine|villain) |research (purposes?|question|paper)|educational purposes?|general knowledge|science (question|project)|chemistry (question|homework)|pharmacology (question|exam)|kahani ke liye|novel ke liye|story ke liye|research ke liye|dost ke liye|friend ke liye|project ke liye|bas (aise hi|curiosity|puch raha|puch rahi|jaanna))\b", re.I)
_DEATH_WORDS = re.compile(r"\b(die|dies|dying|death|dead|kill(s|ed|ing)? (himself|herself|themselves|myself|yourself|oneself|a person|someone)|suicide|suicidal|overdos\w*|od|lethal(ity)?|fatal(ity)?|painless(ly)?|without pain|no pain|peacefully|end (it|it all|their life|his life|her life|a life|my life|your life|one'?s life)|take (their|his|her|my|your|one'?s) (own )?life|not wake up|never wake up|sleep forever|stop (the|their|his|her|my) heart|bleed out|hang(s|ed|ing)?|noose|slit|wrist|poison(s|ed|ing)?|jump(s|ed|ing)? (from|off)|drown(s|ed|ing)?|suffocat\w*|asphyxiat\w*|carbon monoxide|helium|cyanide|sulphas|rat poison|marne|maut|mar (jaye|jaaye|jaun|jaaun|sakta|sakte|sakti|jata|jaata)|khatam ho|jaan (de|le|chali))\b", re.I)
_QUESTION = re.compile(r"(\?|\b(what|which|how|where|when|is it|are there|does|do|would|could|can|should|tell me|explain|describe|list|kitni|kitna|kitne|kaise|kese|kaun ?s[ai]|kon ?s[ai]|kya|kahan|kahaan|batao|bataiye|bata do)\b)", re.I)


class RulesGate:
    """Deterministic regex gate. Returns the level, categories and matched evidence."""

    def assess(self, text: str) -> RiskAssessment:
        if not text or not text.strip():
            return RiskAssessment()
        t = " ".join(text.strip().split())
        cats: dict[str, str] = {}
        for cat, pats in _COMPILED.items():
            for rx in pats:
                m = rx.search(t)
                if m:
                    cats[cat] = m.group(0)
                    break
        if _ATTEMPT_HISTORY.search(t):
            cats["attempt_history"] = _ATTEMPT_HISTORY.search(t).group(0)
        if "method_request" not in cats:
            fr, dw, q = _FRAMING.search(t), _DEATH_WORDS.search(t), _QUESTION.search(t)
            if fr and dw and q:
                cats["method_request"] = f"{fr.group(0)} ... {dw.group(0)}"

        # Idiom filter: only drop an *active ideation* hit when it was caused by a listed idiom and nothing else fires.
        if _IDIOM_OK.search(t):
            hard = re.search(r"\b(suicidal|kill myself|end my life|my own life|marna|aatmahatya|khudkushi|mar jaun|commit suicide)\b", t, re.I)
            if not hard:
                for weak in ("suicide_mention", "suicidal_ideation_active"):
                    ev = cats.get(weak, "").lower()
                    if ev and ev.split()[0] in {"suicide", "end", "ending", "take", "taking", "kill", "killing", "want", "wanna", "dying", "die"}:
                        del cats[weak]

        # Timeframe only matters alongside ideation / harm.
        if "timeframe" in cats and not (set(cats) & {"suicidal_ideation_active", "plan", "means", "intent", "harm_to_others"}):
            del cats["timeframe"]

        level = NONE
        keys = set(cats)
        if keys & _IMMINENT_ALONE:
            level = IMMINENT
        elif (keys & _IDEATION) and (keys & {"plan", "means", "intent"}):
            level = IMMINENT
        elif "suicidal_ideation_active" in keys and "timeframe" in keys:
            level = IMMINENT
        elif len(keys & _ESCALATORS) >= 2:          # means + tonight, plan + means, etc., even without explicit ideation words
            level = IMMINENT
        elif "harm_to_others" in keys and (keys & {"means", "intent", "timeframe", "plan"}):
            level = IMMINENT
        elif keys & _ELEVATED_ALONE:
            level = ELEVATED
        # minor_indicator alone is a routing flag, not a risk level.
        return RiskAssessment(level=level, categories=sorted(keys), evidence=list(cats.values()), source="rules", rules_categories=sorted(keys))


# --------------------------------------------------------------------------------------------
# LLM classifier
# --------------------------------------------------------------------------------------------
class RiskClassifier(Protocol):
    def classify(self, history: list[dict], text: str) -> RiskAssessment | None: ...


class ClaudeRiskClassifier:
    def __init__(self, client, model: str = "claude-haiku-5-5", effort: str = "low"):
        self.client, self.model, self.effort = client, model, effort

    def classify(self, history: list[dict], text: str) -> RiskAssessment | None:
        from .llm import structured_call  # local import keeps `risk` importable without the SDK installed

        ctx = "\n".join(f"{m['role']}: {m['content']}" for m in history[-8:]) or "(no prior context)"
        messages = [{"role": "user", "content": f"Conversation so far:\n{ctx}\n\nLatest user message:\n{text}"}]
        res = structured_call(self.client, model=self.model, system=CLASSIFIER_PROMPT, messages=messages,
                              schema=CLASSIFIER_SCHEMA, effort=self.effort, max_tokens=1024)
        if res.model_answered_badly:
            # The model saw the message and could not give a clean verdict (refusal, truncation, malformed JSON).
            # "When unsure, escalate": treat as IMMINENT so a human looks at it.
            return RiskAssessment(level=IMMINENT, categories=["classifier_unparseable"], evidence=[res.raw[:200]],
                                  source="classifier", confidence=0.0)
        if not res.ok:
            return None                     # API error: the model never saw the text; rules alone decide
        data = res.data
        level = data.get("risk") if data.get("risk") in RISK_LEVELS else IMMINENT   # unknown value -> escalate
        return RiskAssessment(level=level, categories=sorted(set(data.get("categories") or [])),
                              evidence=[data.get("evidence", "")], source="classifier",
                              confidence=float(data.get("confidence") or 0.5))


class RiskGate:
    """Rules first, classifier second; the classifier can only raise the level."""

    def __init__(self, classifier: RiskClassifier | None = None):
        self.rules = RulesGate()
        self.classifier = classifier

    def assess(self, text: str, history: list[dict] | None = None) -> RiskAssessment:
        r = self.rules.assess(text)
        if self.classifier is None:
            return r
        c = self.classifier.classify(history or [], text)
        if c is None:                      # classifier unavailable -> rules stand, but never silently downgrade
            return r
        level = max_level(r.level, c.level)
        return RiskAssessment(level=level, categories=sorted(set(r.categories) | set(c.categories)),
                              evidence=r.evidence + [e for e in c.evidence if e], source="combined",
                              confidence=min(1.0, c.confidence if r.level == NONE else 1.0), rules_categories=list(r.categories))
