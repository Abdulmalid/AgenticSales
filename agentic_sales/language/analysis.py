"""Nigerian register detection, sales-signal extraction and response style planning.

Honest scope: these are transparent lexical/pragmatic heuristics with evidence strings, meant
as a fast first pass and a fallback. The reasoning model refines them (it receives the signals
and evidence), and they are the thing to replace with a trained classifier once labelled data
from the two incoming Nigerian-English corpora exists. They are deliberately multi-label and
return evidence so decisions are auditable.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum


class Register(str, Enum):
    FORMAL = "formal"        # "Good afternoon, sir. I would like to confirm..."
    CASUAL = "casual"        # "Boss, is this thing still available?"
    PIDGIN = "pidgin"        # "Oga, how much be the last price?"
    SOCIAL = "social"        # "Guysss 😂 this thing actually works o."


_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
_WORD = re.compile(r"[a-zA-Z']+")

# (pattern, weight). Weights are small, additive evidence — not proofs.
_PIDGIN = [
    (r"\bdey\b", 2), (r"\bwetin\b", 3), (r"\bwey\b", 2), (r"\babeg\b", 2), (r"\bna\b", 1.5),
    (r"\bno be\b", 2), (r"\bsabi\b", 2), (r"\bwahala\b", 2), (r"\bhow far\b", 2), (r"\bmake i\b", 2),
    (r"\bmake we\b", 2), (r"\bdon\b(?!')", 1), (r"\bunna?\b", 2), (r"\bhow much be\b", 3),
    (r"\bbe the (last|best) price\b", 3), (r"\bi don\b(?!')", 2), (r"\bsend am\b", 2), (r"\bsef\b", 2), (r"\bpikin\b", 2),
    (r"\bcomot\b", 2), (r"\bwan\b", 1), (r"\bbe the\b", 1), (r"\bchop\b", 2), (r"\bpara\b", 2),
    (r"\bstill dey\b", 2), (r"\bnothing do\b", 1), (r"\bfit\b", 0.5), (r"\babi\b", 1.5),
]
_CASUAL = [
    (r"\boga\b", 1), (r"\bboss\b", 2), (r"\bbro\b", 2), (r"\bbros?\b", 1), (r"\bpls\b", 1.5),
    (r"\bplz\b", 1.5), (r"\bthx\b", 1), (r"\bwassup\b", 2), (r"\bhey\b", 1), (r"\byo\b", 1),
    (r"\bthis thing\b", 1), (r"\bu\b", 1.5), (r"\bur\b", 1.5), (r"\bgonna\b", 1), (r"\bwanna\b", 1),
    (r"\bmadam\b", 0.5), (r"\bbtw\b", 1), (r"\bidk\b", 1), (r"\bwhat'?s up\b", 1),
]
_SOCIAL = [
    (r"\bguys+\b", 2), (r"\bomo\b", 2), (r"\bngl\b", 2), (r"\bfr\b", 2), (r"\blol\b", 2),
    (r"\blmao\b", 2), (r"\bsha\b", 1.5), (r"\bbruh\b", 2), (r"\bvibes?\b", 1.5), (r"\bslay\b", 2),
    (r"\bshey\b", 1.5), (r"\bwe move\b", 2), (r"\bno cap\b", 2), (r"\bwahala\b", 0), (r"\bo\b$", 1.5),
]
_FORMAL = [
    (r"\bgood (morning|afternoon|evening)\b", 3), (r"\bsir\b", 1.5), (r"\bkindly\b", 2.5),
    (r"\bi would like to\b", 3), (r"\bplease (confirm|advise|let me know|send)\b", 2.5),
    (r"\bregards\b", 3), (r"\bdear\b", 2), (r"\bwe (are|would) (interested|like)\b", 2),
    (r"\bthank you\b", 1), (r"\bpurchase\b", 1), (r"\binvoice\b", 1.5), (r"\bquotation\b", 2),
    (r"\bat your earliest convenience\b", 3), (r"\bregarding\b", 1.5),
]

# Additions informed by the owner's labelled Nigerian messages (customer_messages_naija.jsonl):
# "social" there means rapport-building talk (greetings, well-wishing, compliments on the page),
# not only emoji/slang; "casual" includes relaxed-but-polite English.
_SOCIAL += [
    (r"\bgod bless\b", 3), (r"\bhope (you|your|the business|business|all)\b", 3),
    (r"\bhow is (the )?(market|business|your day|family|work)\b", 3), (r"\bhi dear\b", 3),
    (r"\bhello dear\b", 3), (r"\byour page\b", 2.5), (r"\bi saw you on\b", 2.5),
    (r"\blove what you (posted|post)\b", 3), (r"\bthanks for (replying|responding|getting back)\b", 2.5),
    (r"\byour hustle\b", 3), (r"\bhope you('re| are) (doing )?well\b", 3), (r"\bhad a good day\b", 2.5),
]
_CASUAL += [
    (r"\bquick (question|one)\b", 2.5), (r"\bjust one (question|thing)\b", 2.5), (r"\bno worries\b", 2),
    (r"\bno rush\b", 1.5), (r"^hi\b", 1), (r"\bhow far\b", 1), (r"\bbtw\b", 1), (r"\bhey\b", 1),
]
_PIDGIN += [
    (r"\b(hold|give|send|carry|take|buy|sell|pay|do|see|check|bring|collect|break|reduce|confirm) am\b", 3),
    (r"\bi go (pay|buy|come|send|get|give|take|call|wait)\b", 3), (r"\byou go (give|sell|reduce|send)\b", 3),
    (r"\bno (work|fit|dey|go|get|want|even|too|vex|wahala)\b", 2), (r"\bmy guy\b", 2),
    (r"\bsmall small\b", 2.5), (r"\bnow now\b", 2.5), (r"\blast last\b", 2.5), (r"\byarn\b", 2.5),
    (r"\bdis\b", 2), (r"\bdat\b", 2), (r"\bdi (price|one|money)\b", 2), (r"\bgree\b", 2.5),
    (r"\bdey\b", 0.5), (r"\bwe dey\b", 1),
]


def _score(text: str, table: list[tuple[str, float]]) -> tuple[float, list[str]]:
    total, ev = 0.0, []
    for pat, w in table:
        if w and re.search(pat, text):
            total += w
            ev.append(re.search(pat, text).group(0))
    return total, ev


@dataclass(frozen=True)
class RegisterReading:
    primary: Register
    scores: dict[str, float]
    evidence: dict[str, list[str]]
    confidence: float           # 0..1, low for very short/ambiguous messages
    mixed: bool                 # code-switching: two registers both strongly present
    informal_prob: float | None = None  # P(casual)+P(pidgin) from the calibrated model, if available


def _detect_heuristic(text: str) -> RegisterReading:
    t = text.lower().strip()
    words = _WORD.findall(t)
    n = max(len(words), 1)
    pid, pid_ev = _score(t, _PIDGIN)
    cas, cas_ev = _score(t, _CASUAL)
    soc, soc_ev = _score(t, _SOCIAL)
    frm, frm_ev = _score(t, _FORMAL)

    emojis = len(_EMOJI.findall(text))
    if emojis:
        soc += min(emojis, 3) * 1.0
        soc_ev.append(f"{emojis} emoji")
    if re.search(r"([a-z])\1{2,}", t):
        soc += 1.5
        soc_ev.append("letter elongation")
    # polished prose: capitalised sentence start + terminal punctuation + no texting shorthand
    if text[:1].isupper() and re.search(r"[.?!]$", text.strip()) and cas + pid + soc == 0:
        frm += 1.0
        frm_ev.append("capitalised, punctuated sentence")

    scores = {Register.FORMAL.value: frm, Register.CASUAL.value: cas,
              Register.PIDGIN.value: pid, Register.SOCIAL.value: soc}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top, second = ranked[0], ranked[1]
    if top[1] == 0:
        # no evidence either way: plain English, treat as formal-neutral (safest default)
        primary, conf = Register.FORMAL, 0.2
    else:
        primary = Register(top[0])
        margin = (top[1] - second[1]) / (top[1] + 1e-9)
        conf = min(1.0, (0.35 + 0.65 * margin) * min(1.0, 0.4 + n / 12))
    mixed = second[1] >= 0.6 * top[1] and top[1] > 0 and second[1] >= 2
    return RegisterReading(primary, scores,
                           {Register.FORMAL.value: frm_ev, Register.CASUAL.value: cas_ev,
                            Register.PIDGIN.value: pid_ev, Register.SOCIAL.value: soc_ev},
                           round(conf, 2), mixed)


# ---------------------------------------------------------------- sales signals

_SIGNALS: dict[str, list[str]] = {
    "price_inquiry": [r"\bhow much\b", r"\bprice\b", r"\bwhat'?s the cost\b", r"\bhow mush\b",
                      r"\bna how much\b", r"\bwetin be the price\b", r"₦|\bngn\b"],
    "negotiation": [r"\blast price\b", r"\bdiscount\b", r"\breduce\b", r"\bnegotiable\b",
                    r"\bcan you do\b", r"\bbest price\b", r"\bsmall (small )?(am|reduce)\b",
                    r"\bdrop (it|the price)\b", r"\bbe the last\b", r"\bhammer\b"],
    "availability_check": [r"\bstill available\b", r"\bin stock\b", r"\bavailable\b", r"\bstill dey\b"],
    "trust_concern": [r"\blegit\b", r"\bis this real\b", r"\bscam\b", r"\bfake\b", r"\bcan i trust\b",
                      r"\bpay on delivery\b", r"\bpod\b", r"\bcod\b", r"\bproof\b", r"\bseen (a|your) (shop|office)\b",
                      r"\bno be (419|scam)\b"],
    "delivery_concern": [r"\bdeliver", r"\bshipping\b", r"\bdispatch\b", r"\bhow long\b",
                         r"\bwhen (will|can) i (get|receive)\b", r"\bwaybill\b", r"\bpark\b"],
    "payment_claim": [r"\bi (have |don )?(paid|sent|transferred)\b", r"\bpayment (made|done|sent)\b",
                      r"\bcheck your (account|bank)\b", r"\bdebit alert\b", r"\bscreenshot\b",
                      r"\bi don pay\b", r"\bmoney don enter\b", r"\bstill pending\b"],
    "payment_method": [r"\bbank transfer\b", r"\bussd\b", r"\bpos\b", r"\bpaystack\b", r"\bopay\b",
                       r"\bcard\b", r"\baccount number\b", r"\bpay on delivery\b"],
    "stalling": [r"\bget back to you\b", r"\bi'?ll (let you know|think|call)\b", r"\bi go (tell|call|reach)\b",
                 r"\blet me (think|check|ask)\b", r"\bmaybe later\b", r"\bnext (week|month)\b",
                 r"\bi want to (think|consult)\b"],
    "ready_to_buy": [r"\bi('ll| will| want to| wan) (take|buy|order|pay)\b", r"\bsend (me )?(the )?(account|details|link)\b",
                     r"\bhow do i pay\b", r"\bi want (this|it|the)\b", r"\bplace (the|my) order\b",
                     r"\bi'?m ready\b", r"\bi go buy\b", r"\blet'?s do (it|this)\b"],
    "urgency": [r"\burgent", r"\basap\b", r"\btoday\b", r"\bright now\b", r"\bimmediately\b",
                r"\bquick quick\b", r"\bquickly\b", r"\bsharp\b", r"\bgift\b", r"\btomorrow\b"],
    "bulk_or_reseller": [r"\bwholesale\b", r"\bbulk\b", r"\breseller\b", r"\bresell\b", r"\b\d{2,}\s*(units|pieces|pcs)\b",
                         r"\bdistributor\b", r"\bfor my (shop|store|customers)\b"],
    "competitor_comparison": [r"\bcheaper\b", r"\bsomeone (else )?(is )?(selling|offering)\b", r"\bat .{0,20}(jiji|jumia|konga)\b",
                              r"\bother (vendor|seller|shop)s?\b", r"\bsaw (it|this) for\b"],
    "pressure_tactic": [r"\bdo it now or\b", r"\bthe owner (said|told|approved)\b", r"\bi know the (ceo|owner|manager)\b",
                        r"\bdon'?t (waste|delay)\b", r"\bsend (the )?(goods|item|product) first\b",
                        r"\bi'?ll pay (after|when it arrives)\b", r"\bsend (it )?before (i|the) pay"],
    "complaint_or_refund": [r"\brefund\b", r"\bmoney back\b", r"\bdamaged\b", r"\bnot (what|as) (i )?(ordered|described)\b",
                            r"\bcomplain", r"\bdisappointed\b", r"\bnever (got|received)\b"],
    "returning_customer": [r"\bagain\b", r"\blast time i (bought|ordered)\b", r"\bmy (last|previous) order\b",
                           r"\bi bought (from you|before)\b"],
    "referral": [r"\b(referred|recommended) (me|by)\b", r"\bsent me\b", r"\b(my friend|someone) told me\b"],
}
# Additions informed by the owner's labelled Nigerian messages. Written as general cue families
# (verbs + objects, Pidgin and standard forms), not sentence copies.
_SIGNALS["price_inquiry"] += [
    r"\btotal (cost|price|amount)\b", r"\bwhat('s| is) the total\b", r"\bhow much (is )?(the )?total\b",
    r"\btotal how much\b", r"\bwhich plan\b", r"\bsend (me )?(the )?(list|catalogue|pictures|price)\b",
    r"\bwetin you dey sell\b", r"\bstill dey sell\b", r"\binterested in (purchasing|buying|the)\b",
    r"\b(want|wan) to (buy|order)\b", r"\bplace an? order\b", r"\bhow much (you|una) (fit )?sell\b",
    r"\bask about the\b", r"\bwhat'?s the price\b", r"\bwhat (is|are) (the|your) (price|prices|rate)\b",
]
_SIGNALS["negotiation"] += [
    r"\btoo (costly|much|high|expensive|dear)\b", r"\bcheapest\b", r"\bbetter price\b", r"\bprice (no work|is final|final|too|negotiable|higher)\b",
    r"\bcan you do (better|[\[\d₦])", r"\bbreak am\b", r"\byarn\b", r"\btry small\b", r"\bmake i give you\b",
    r"\bi (no )?get small money\b", r"\bcannot pay more\b", r"\bpay half\b", r"\b\d+% now\b",
    r"\babove my budget\b", r"\bout of my budget\b", r"\bthe other (seller|person|vendor)\b", r"\bno work for me\b",
    r"\bbulk\b", r"\bregular customer\b", r"\bnegotiate\b", r"\bfor less\b", r"\bdey sell am for less\b",
    r"\bprice (is )?(final|high)\b", r"\bgive me (a )?(better|good) price\b",
]
_SIGNALS["payment_claim"] += [
    r"\bi (have |don |just |already )?(made|send|sent|transfer|transferred|pay|paid|do|did)\b.{0,25}\b(transfer|payment|alert|money|naira|am)\b",
    r"\bi (have |don |just |already )?made (the |a |my )?(payment|transfer)\b", r"\b(check|see) (your |the |my )?alert\b",
    r"\balert (don|has|have)?\s*(enter|land|reach|drop)", r"\b(don|has|have) reach(ed)? you\b", r"\bsend the alert\b",
    r"\b(payment|transfer) (went through|has reflected|reflected|don reach)\b", r"\bhas it reflected\b",
    r"\bplease confirm (receipt|payment|the transfer)\b", r"\bconfirm (when|if) you see\b", r"\bi (will|go) (send|pay|transfer).{0,20}\bnow( now)?\b",
    r"\bmade payment\b", r"\bthe (account|transfer) (you sent|i made)\b", r"\battached the receipt\b",
]
_SIGNALS["stalling"] += [
    r"\bpay (on|upon) delivery\b", r"\bpay when i (receive|see|get|have)\b", r"\bwhen i (receive|have the cash|see the thing)\b",
    r"\b(upon|on) delivery\b", r"\bafter delivery\b", r"\bhold (it|the item|one|am)\b.{0,15}\b(for me)?\b", r"\bsalary\b",
    r"\bask my (husband|wife|oga|boss|friend|partner)\b", r"\bfirst see\b", r"\bwithin \d+ hours\b", r"\bi (will|go) pay.{0,20}(next|tomorrow|later|small small|weekend)\b",
    r"\bnext week\b", r"\bno (too )?rush\b", r"\bi have not paid yet\b", r"\bhalf now\b", r"\bbalance on delivery\b",
    r"\byou no dey reply\b", r"\bstill dey wait\b", r"\bhave to (ask|check|consult)\b", r"\bbefore you send\b",
    r"\bi will only (pay|release)\b", r"\bi go pay (when|after|small)\b", r"\bkeep one for me\b", r"\blet you know\b",
]
_SIGNALS["trust_concern"] += [
    r"\bscam(med)?\b", r"\bdup(e|ing)?\b", r"\bdisappear\b", r"\bcollect my money\b", r"\bverif(y|ied)\b", r"\bcac\b",
    r"\bbusiness registration\b", r"\bcustomer references\b", r"\breferences\b", r"\bbad review\b", r"\bhesitant\b",
    r"\breturn policy\b", r"\bno dey fear\b", r"\btrust me\b", r"\bhow i go know\b", r"\bi don hear say\b", r"\bonly pay into\b",
    r"\bnot purchased from you\b", r"\bnever (bought|purchased) from you\b", r"\bis it true\b", r"\bcompany name\b",
    r"\bsend your account number first\b", r"\bi go pay before you send\b",
]

# Second round (cue families from the first holdout's dev half; a sealed half is never inspected).
_SOCIAL += [(r"\bsaw your (tiktok|instagram|video|post|page|story)\b", 3), (r"\bi love (the|this|your)\b", 2.5)]
_SIGNALS["ready_to_buy"] += [
    r"\bi (want|wan|would like|'d like) (to )?(place|order|get|buy)\b", r"\bi (want|wan) (am|it|this|the|one)\b", r"\bplace an? order\b",
    r"\bi (am|'m) placing (the|an|my) order\b", r"\bcan i get the\b", r"\bi (will|go|dey) (make|ready to|pay)\b.{0,15}\b(transfer|payment|pay|now)\b",
    r"\bready to pay\b", r"\b(make i|let me|if i) pay (now|half|first|today)\b", r"\bi (will|go) pay (now|once|today|this)\b",
    r"\bclose the deal\b", r"\bsend (me )?(the )?account( number)?\b", r"\bi will pay\b", r"\bi (will|go) make (the )?(transfer|payment)\b",
    r"\bpay (half|50%|deposit) now\b", r"\bto hold one\b", r"\bif i buy\b", r"\bi need (am|it|this)\b",
]
_SIGNALS["delivery_concern"] += [
    r"\bship(ping)? to\b", r"\bget to me\b", r"\bwhen (can|will|go) (it|i|you).{0,12}(get|reach|arrive|deliver)\b", r"\bno reach\b",
    r"\bwhen i receive\b", r"\bsame.day\b", r"\bfree delivery\b", r"\bwith delivery\b", r"\bdelivery fee\b", r"\bdispatch\b",
    r"\bwhen you go deliver\b", r"\bwill pay when i receive\b",
]
_SIGNALS["urgency"] += [
    r"\bnow now\b", r"\bsharp sharp\b", r"\bthis morning\b", r"\bsince morning\b", r"\bbefore close of work\b",
    r"\bi need (am|it)\b.{0,20}\b(now|today|sharp)\b", r"\bsame.day\b", r"\bbefore (the )?(weekend|friday|saturday|event)\b",
]
_SIGNALS["stalling"] += [
    r"\b(make i|let me|i dey|i go|i will|i need to) think\b", r"\bgive me (small |some )?time\b", r"\btill tomorrow\b", r"\bi dey save\b",
    r"\bwhen (the )?money reach\b", r"\bmoney go enter\b", r"\bno wan rush\b", r"\bverify before\b", r"\bnot sure\b",
    r"\bjust budgeting\b", r"\border next month\b", r"\bsend (me )?the catalog", r"\bi dey think\b",
]
_SIGNALS["negotiation"] += [
    r"\bbulk discount\b", r"\bstudent discount\b", r"\bany (free )?(delivery|discount)\b", r"\bhow much you go give me\b",
    r"\bcharge me more\b", r"\bwhy (you|your).{0,30}(more|higher)\b", r"\bsame thing my friend\b", r"\bcheapest\b",
    r"\bvs wetin you\b", r"\bsmall money (i|na)\b", r"\bpay extra\b", r"\bhigher than\b",
]
_SIGNALS["price_inquiry"] += [r"\bcheapest\b", r"\bbulk discount and total\b", r"\bhow much for\b", r"\btotal and\b", r"\bsize chart\b"]
_SIGNALS["trust_concern"] += [
    r"\bdey scam\b", r"\bscam person\b", r"\bsell same thing\b", r"\bmy friend buy\b", r"\bcharge me more\b",
    r"\bverify before any payment\b",
]
_SIGNALS["payment_claim"] += [r"\bmake (the |a )?(transfer|payment)\b", r"\bthe money don enter\b", r"\bmoney don enter\b"]

_COMPILED = {k: [re.compile(p, re.I) for p in pats] for k, pats in _SIGNALS.items()}


@dataclass(frozen=True)
class Signal:
    name: str
    evidence: str


def extract_signals(text: str) -> list[Signal]:
    """Multi-label, evidence-bearing. 'How much?' yields only price_inquiry: it does NOT imply
    purchase intent, and downstream scoring must not treat it as such."""
    out = []
    for name, rxs in _COMPILED.items():
        for rx in rxs:
            m = rx.search(text)
            if m:
                out.append(Signal(name, m.group(0)))
                break
    names = {s.name for s in out}
    if "negotiation" in names:
        # the bare word "price" inside haggling ("last price?", "that price no work") is not an inquiry
        out = [s for s in out if not (s.name == "price_inquiry" and s.evidence.lower() in ("price", "prices"))]
    return out


# ---------------------------------------------------------------- style planning

class Slang(int, Enum):
    NONE = 0       # standard professional English
    LIGHT = 1      # warm, contractions, an occasional local expression
    NATIVE = 2     # fully mirrors customer (Pidgin / social) — only if they lead


@dataclass(frozen=True)
class StylePlan:
    register: Register
    slang: Slang
    emoji: bool
    formality: str
    guidance: str
    reasons: list[str] = field(default_factory=list)


# Topics where clarity beats flavour: never use Pidgin/slang for the operative sentence.
_PRECISION_SIGNALS = {"payment_claim", "payment_method", "pressure_tactic", "complaint_or_refund"}


def plan_style(reading: RegisterReading, signals: list[Signal], brand_voice: str = "",
               allow_pidgin: bool = True) -> StylePlan:
    """Mirror the customer, but never lead more informally than they do, and drop to plain
    English on payment/fraud/policy specifics. Mixed or low-confidence readings stay plain."""
    names = {s.name for s in signals}
    reasons: list[str] = []
    reg, conf = reading.primary, reading.confidence

    if reading.informal_prob is not None and reg is not Register.SOCIAL:
        # calibrated model: decide formal-vs-informal first, then which informal register
        ip = reading.informal_prob
        pid, cas = reading.scores["pidgin"], reading.scores["casual"]
        if ip < 0.4:
            reg_out, slang = Register.FORMAL, Slang.NONE
        elif ip < 0.55:
            reasons.append("formal/informal uncertain -> plain professional English")
            reg_out, slang = Register.FORMAL, Slang.NONE
        elif pid >= 0.5 and pid > cas and allow_pidgin:
            reg_out, slang = Register.PIDGIN, Slang.NATIVE
        else:
            reg_out, slang = Register.CASUAL, Slang.LIGHT
            if pid > cas and not allow_pidgin:
                reasons.append("business voice disallows Pidgin")
    elif conf < 0.45 or reading.mixed and conf < 0.6:
        reasons.append("low-confidence/mixed reading -> plain professional English")
        reg_out, slang = Register.FORMAL, Slang.NONE
    elif reg is Register.FORMAL:
        reg_out, slang = Register.FORMAL, Slang.NONE
    elif reg is Register.CASUAL:
        reg_out, slang = Register.CASUAL, Slang.LIGHT
    elif reg is Register.PIDGIN and allow_pidgin:
        reg_out, slang = Register.PIDGIN, Slang.NATIVE
    elif reg is Register.PIDGIN:
        reg_out, slang = Register.CASUAL, Slang.LIGHT
        reasons.append("business voice disallows Pidgin")
    else:  # SOCIAL
        reg_out, slang = Register.SOCIAL, Slang.LIGHT

    if names & _PRECISION_SIGNALS and slang is not Slang.NONE:
        slang = Slang.LIGHT if slang is Slang.NATIVE else slang
        reasons.append("payment/policy specifics: state the key facts in plain English")

    emoji = reg_out in (Register.SOCIAL, Register.CASUAL) and "complaint_or_refund" not in names
    formality = {Register.FORMAL: "formal", Register.CASUAL: "relaxed", Register.PIDGIN: "informal",
                 Register.SOCIAL: "playful"}[reg_out]
    guidance = {
        Slang.NONE: "Standard professional English. No slang, no Pidgin. Courteous and direct.",
        Slang.LIGHT: ("Warm and conversational standard English. Contractions are fine. At most one "
                      "light local expression if it fits naturally; do not force any."),
        Slang.NATIVE: ("Mirror the customer's Pidgin naturally and sparingly. Keep prices, dates, "
                       "payment details and policy statements in clear English. Never caricature."),
    }[slang]
    if brand_voice:
        guidance += f" Brand voice: {brand_voice}."
    return StylePlan(reg_out, slang, emoji, formality, guidance, reasons)


# ---------------------------------------------------------------- learned register model

_NB_WEIGHT_HEURISTIC = 1.0   # chosen on a held-out split of the corpus labels (see language/train.py)
_NB_TEMPERATURE = 16.0       # fitted on held-out NLL; raw Naive Bayes is wildly overconfident
_nb_cache: dict | None = None


def _nb() -> dict | None:
    """Naive-Bayes model trained by `python -m agentic_sales.language.train` (None if not trained)."""
    global _nb_cache
    if _nb_cache is None:
        from .train import MODEL_PATH
        import json
        _nb_cache = json.loads(MODEL_PATH.read_text(encoding="utf-8")) if MODEL_PATH.exists() else {}
    return _nb_cache or None


def detect_register(text: str) -> RegisterReading:
    """Formal / casual / Pidgin from a classifier trained on corpus-labelled customer messages,
    blended with the lexical heuristics; social-media style (no labelled data exists) stays heuristic.
    Falls back to heuristics alone if the model has not been trained."""
    heur = _detect_heuristic(text)
    model = _nb()
    if model is None:
        return heur
    from .train import features
    feats = set(features(text))
    known = [f for f in feats if f in model["vocab"]]
    h = heur.scores
    # social style is detected lexically/orthographically (emoji, elongation, slang particles)
    if heur.primary is Register.SOCIAL and h["social"] >= 2.5:
        return heur
    if not known and max(h.values()) == 0:
        return heur  # nothing to go on: keep the safe plain-English default
    classes = model["classes"]
    sc = {c: 0.0 for c in classes}  # uniform prior: the corpus class balance is not the deployment prior
    for f in feats:
        v = model["vocab"].get(f)
        if v:
            for c in classes:
                sc[c] += v[c]
    for c in classes:
        sc[c] += _NB_WEIGHT_HEURISTIC * h[c]
    m = max(sc.values())
    z = sum(math.exp((v - m) / _NB_TEMPERATURE) for v in sc.values())
    prob = {c: math.exp((sc[c] - m) / _NB_TEMPERATURE) / z for c in classes}
    ranked = sorted(prob.items(), key=lambda kv: kv[1], reverse=True)
    top, second = ranked[0], ranked[1]
    n = max(len(_WORD.findall(text)), 1)
    conf = round(min(1.0, top[1] * min(1.0, 0.4 + n / 10)), 2)
    if conf < 0.3 and max(h.values()) == 0:
        return heur  # too little signal: plain-English default rather than a guess
    # most class-indicative tokens present in the message (log-likelihood ratio vs. other classes)
    def llr(f: str) -> float:
        v = model["vocab"][f]
        return v[top[0]] - max(v[c] for c in classes if c != top[0])
    cues = [f for f in sorted(known, key=llr, reverse=True)[:4] if llr(f) > 0.7]
    evidence = {k: list(v) for k, v in heur.evidence.items()}
    evidence[top[0]] = evidence.get(top[0], []) + [f"model:{f}" for f in cues]
    scores = {**{c: round(prob[c], 3) for c in classes}, Register.SOCIAL.value: round(h["social"], 2)}
    return RegisterReading(Register(top[0]), scores, evidence, conf,
                           mixed=second[1] >= 0.6 * top[1] and top[1] < 0.75,
                           informal_prob=round(prob["casual"] + prob["pidgin"], 3))
