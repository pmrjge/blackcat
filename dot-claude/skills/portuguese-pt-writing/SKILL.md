---
name: portuguese-pt-writing
description: Load before writing, translating or proofreading anything in European Portuguese (Portugal, pt-PT), not Brazilian — AO1990 spelling and traps, PT vs BR vocabulary and grammar (clitic placement, estar a + infinitivo, tu/você/o senhor), punctuation and typography (« », numbers, euros, dates), formal letters and requerimentos to public services, IT and maths terminology, English false friends.
---
# European Portuguese (pt-PT): writing, translation, proofreading

## Scope
- Target: Portuguese as written in Portugal under the Acordo Ortográfico de 1990 (AO1990). Not Brazilian (pt-BR);
  if the audience is Brazilian or mixed, ask first — never blend the two.
- Covers spelling, vocabulary, grammar, typography, formal correspondence, terminology, translation from English,
  tone. General structure and clarity: `technical-writing`. LaTeX specifics (babel `portuguese`,
  `\sisetup{output-decimal-marker={,}}`): `latex-typesetting`. Typesetting details (fonts, OpenType, spacing):
  `typography`.
- Authorities to check doubtful points (in this order): Vocabulário Ortográfico do Português (VOP, ILTEC, on the
  Portal da Língua Portuguesa) and its Lince converter; Ciberdúvidas da Língua Portuguesa
  (ciberduvidas.iscte-iul.pt); dictionaries Infopédia (Porto Editora) and Priberam (marks PT/BR variants); the EU
  *Código de Redação Interinstitucional* (style-guide.europa.eu/pt) for numbers, currency and quotation marks;
  the Microsoft *Portuguese (Portugal) Localization Style Guide* and Microsoft Terminology for software UI;
  IATE (iate.europa.eu) for EU/legal/technical terms; the *Livro de Estilo* of justica.gov.pt for plain language.

## 1. Spelling (AO1990)
In force in Portugal since 13 May 2009; transition ended 13 May 2015; adopted in schools from September 2011 and
by the State (incl. Diário da República) from January 2012. Default to AO1990. Some publishers and clients still
use pre-AO spelling — ask, then apply one norm consistently (Lince converts pre-AO text).
- **Mute c/p dropped:** ação, ótimo, direção, diretor, atual, exato, coleção, adoção, batizar, Egito (but egípcio).
  **Pronounced consonants stay:** pacto, compacto, ficção, convicção, adepto, apto, rapto, núpcias.
  PT pronunciation decides, so PT and BR still differ: receção, perspetiva, espetador, conceção, aspeto, respetivo
  (PT) vs recepção, perspectiva, espectador, concepção, aspecto, respectivo (BR).
- **Facultative double spellings** (Base IV): aspeto/aspecto, carateres/caracteres, dição/dicção, facto/fato,
  setor/sector, cato/cacto. In PT write **facto** (in PT *fato* = suit) and **contacto**; pick one of the others
  per document.
- **Acute vs circumflex:** before m/n PT uses the acute where BR uses the circumflex — género, académico,
  económico, fenómeno, prémio, António, ténis, bebé (BR gênero, acadêmico, econômico, fenômeno, prêmio…).
- **Accents removed:** para (verb *parar*), pelo, polo, pera. Kept: pôr (verb), pôde (past). Facultative:
  amámos/amamos (PT keeps the acute for the past tense: "ontem enviámos"), dêmos/demos, fôrma/forma.
- **Hyphen:** no hyphen in locutions — fim de semana, dia a dia, cão de guarda, sala de jantar; exceptions keep it:
  água-de-colónia, cor-de-rosa, mais-que-perfeito, pé-de-meia, à queima-roupa, ao deus-dará. hei de, hás de,
  hão de (no hyphen). Prefix + same vowel → hyphen: anti-inflamatório, micro-ondas, auto-observação;
  prefix + r/s → doubled: antirreligioso, contrarregra, antissemita, cosseno; co- fuses: coautor, coordenar.
- **Lower case:** months, seasons, weekdays (setembro, primavera, segunda-feira). **Facultative capitals**
  (choose once): disciplines (matemática/Matemática), forms of address (senhor doutor/Senhor Doutor), street
  categories (rua/Rua), words after the first in titles of works (*Memorial do convento/Convento*).
- **PT-specific forms:** registo, registar (BR registro, registrar); controlo (BR controle); equipa (BR equipe);
  facto (BR fato).
- **Frequent errors:** há (exists/ago) vs à (a + a) vs a; "havia muitas pessoas" (impersonal *haver*, never
  "haviam"); *porque* in direct questions in PT ("Porque não vieste?", "Porque é que…?"), *porquê* at the end or
  as a noun ("Não sei porquê.", "o porquê"), *por que* = "por qual" ("a razão por que saiu"); BR writes "Por que…?".

## 2. PT vs BR vocabulary
| English | pt-PT | pt-BR |
|---|---|---|
| screen / touchscreen | ecrã / ecrã tátil | tela / tela sensível ao toque |
| mobile phone | telemóvel | celular |
| file / folder | ficheiro / pasta | arquivo / pasta |
| user | utilizador | usuário |
| mouse | rato | mouse |
| download / upload | transferir / carregar | baixar, fazer download / enviar, fazer upload |
| password | palavra-passe | senha |
| sign in / sign out | iniciar sessão / terminar sessão | entrar, fazer login / sair |
| settings | definições | configurações |
| save / delete / share | guardar / eliminar / partilhar | salvar / excluir / compartilhar |
| app | aplicação (app) | aplicativo (app) |
| desktop (screen) | ambiente de trabalho | área de trabalho |
| screenshot | captura de ecrã | captura de tela |
| laptop / USB stick | portátil / pen (USB) | notebook / pen drive |
| database | base de dados | banco de dados |
| machine / deep / reinforcement learning | aprendizagem automática / profunda / por reforço | aprendizado de máquina / profundo / por reforço |
| neural network | rede neuronal | rede neural |
| training (a model) | treino | treinamento |
| eigenvalue / eigenvector | valor próprio / vetor próprio | autovalor / autovetor |
| sequence (analysis) | sucessão | sequência |
| the integral | o integral (usual in PT university texts; Infopédia gives *a integral*, Priberam both) | a integral |
| billion (10⁹) / trillion (10¹²) | mil milhões / bilião | bilhão / trilhão |
| bus / train | autocarro / comboio | ônibus / trem |
| breakfast | pequeno-almoço | café da manhã |
| bathroom / fridge / juice | casa de banho / frigorífico / sumo | banheiro / geladeira / suco |
| team | equipa | equipe (football: time) |
| pedestrian crossing / toll | passadeira / portagem | faixa de pedestres / pedágio |
| driving licence | carta de condução | carteira de motorista (CNH) |
| suit (clothes) | fato | terno |
| girl | rapariga (neutral in PT; offensive in parts of Brazil) | moça, garota |
| queue | fila (*bicha* is dated and offensive in BR — avoid) | fila |
Keep English where Portuguese practice keeps it: software, hardware, e-mail/email (formal: correio eletrónico),
online, cookie, bit, byte, pixel, blog, streaming, startup; in developer contexts commit, branch, pull request.
Do not translate code, commands, API names or product UI strings — use the product's official pt-PT strings.
Units: 1,5 GB, 3 GHz (unit symbols are never pluralised or translated).

## 3. Grammar
- **Clitic placement (the most visible PT/BR difference).** European Portuguese default is **enclisis** in
  affirmative main clauses: "Disse-me que vinha." "Enviei-lhe o ficheiro." A sentence never begins with an
  unstressed pronoun ("Me disse" is Brazilian). **Proclisis** when, without a pause, the verb is preceded by:
  negation (não, nunca, ninguém, nada, jamais); a subordinating conjunction or relative (que, se, quando, porque,
  embora, onde); an interrogative or exclamative; adverbs such as já, ainda, sempre, só, também, bem, mal, talvez;
  indefinites/quantifiers (alguém, todos, tudo, ambos); or in optative sentences ("Deus o ajude").
  Examples: "Não me disse." "Já lhe enviei." "Espero que se resolva." "Quem te contou?"
- **Mesoclisis** (future and conditional, formal register): "enviar-lhe-ei", "far-se-ia"; with a trigger →
  proclisis ("não lhe enviarei"); in neutral prose prefer a periphrasis ("vou enviar-lhe").
- **Pronoun contractions:** o/a/os/as after -r/-s/-z → lo/la ("enviá-lo", "fizemo-lo", "fá-la"); after nasal →
  no/na ("enviaram-no").
- **Progressive:** "estar a + infinitivo" — "Estou a trabalhar" (BR "Estou trabalhando"). The gerund remains in
  PT for adverbial clauses ("Sabendo isto, decidimos…") and in some regional speech.
- **Articles with possessives:** "o meu computador", "a nossa proposta" (usual in PT).
- **Forms of address:** *tu* for family, friends, peers, and much informal marketing/UI copy; for polite
  address use the third person without a pronoun ("Pode enviar-me…?"), the name or title ("O Nuno concorda?",
  "A Dra. Ana confirma?") or "o senhor/a senhora". Avoid *você* in writing — in Portugal it can read as
  condescending or oddly familiar; Microsoft's pt-PT guide also says to rephrase around it ("Não pode fechar…",
  "Recomendamos que verifique…"). Official: *V. Ex.ª* (Vossa Excelência) with third-person verb and *sua*
  ("Venho solicitar a V. Ex.ª que se digne…"). Plural: *vocês* (+ 3rd plural); *vós* is archaic/regional.
- **UI and instructions:** imperative in the polite third person — "Selecione", "Clique", "Guarde o ficheiro".
- **"A gente"** = colloquial "nós", verb in 3rd singular ("a gente vai"); avoid in formal text.
- **Obligation:** "ter de" preferred in careful writing ("Tem de assinar"); "ter que" is common in speech.
- **Prepositions** (Microsoft pt-PT guide): "converter em" (not *para*), "registar em", "definir como".
- **Punctuation:** no comma between subject and verb; no comma before *e* in a simple enumeration; lower case
  after a colon (except proper nouns and quoted sentences).

## 4. Punctuation and typography
- **Quotation marks:** « » first level, “ ” second, ‘ ’ third: «Os homens devem “ser compreensivos, ‘bons’, e
  respeitosos” dos seus iguais.» Final punctuation inside only if the whole sentence is quoted:
  O chefe disse: «O Albino está despedido!» — but: O artigo diz que «as aspas vêm antes do ponto».
- **Travessão (—)** with spaces for parentheticals and dialogue: "As condições — ordenado e subvenções — eram boas."
  Dialogue: "— Porquê? — perguntou este." Comma after the closing dash if needed: "Sim — disse a Amélia —, vou."
  Hyphen (-) for compounds and attached pronouns, never spaced; numeric ranges with a hyphen or an en dash
  (1980-1990 / 1980–1990) — one convention per document.
- **Numbers:** decimal comma; thousands grouped in threes by a (non-breaking) space, not a point:
  152 231,324567 (EU style guide); four-digit numbers are commonly left ungrouped (1234) — follow house style;
  years never grouped. In lists or coordinates with decimals, separate by semicolons: (1,5; 2,0).
  Keep the decimal point inside code, data files and CLI examples.
- **Percent and degrees:** EU style "15 %", "39 °C" with a non-breaking space; "15%" is common in the press —
  pick one per document.
- **Currency:** after the amount, separated by a space: "12,50 €" (general), "12 500 EUR" (EU legal texts,
  where the ISO code is compulsory); other currencies spelled out at first mention, then the code:
  "300 coroas dinamarquesas (DKK) … 505 DKK". Large amounts: "1,326 mil milhões de euros".
- **Dates and times:** "26 de setembro de 2026" (month lower case); "sábado, 26 de setembro"; numeric 26/09/2026
  or 26.9.2026 (EU references); ISO 2026-09-26 in technical and data contexts. Times: "18h30" (h without point or
  spaces, EU style); "18:30" in timetables and UIs; 24-hour clock.
- **Ordinals:** period + superscript º/ª — 1.º, 2.ª, 3.º andar, artigo 102.º, n.º 1 (use º U+00BA / ª U+00AA,
  never the degree sign °).
- **Abbreviations:** Sr., Sr.ª, Dr., Dr.ª, Eng.º, Eng.ª, Prof., Prof.ª, Exmo./Ex.mo, Exma./Ex.ma (both spellings
  accepted — Ex.mo when the ending is superscript), V. Ex.ª, n.º, p. ex., etc. Acronyms: capitals, no points, no
  plural mark ("as PME").
- No space before : ; ! ? (unlike French). Maths: open intervals are often written ]a, b[ in Portugal — follow
  the venue.

## 5. Formal correspondence
**E-mail or letter to a public service or institution**
```text
Assunto: Pedido de <o quê> — processo n.º <referência>

Exmos. Senhores,                      (or: Exma. Senhora Diretora, / Exmo. Senhor Dr. <Apelido>,)

<Who you are, only as needed, and the purpose in one sentence, with the reference number.>
<Facts: dates, what was already done, what is missing.>
<The request, precise and actionable: "Solicito que me seja enviado…", "Venho solicitar a V. Ex.ª…".>
Junto em anexo: <list>.

Com os melhores cumprimentos,
<Nome completo>
<Contacto>
```
Closings used in Portugal: "Com os melhores cumprimentos" (default), "Cumprimentos", "Atentamente",
"Atenciosamente". Addressee block in a letter: "Exma. Senhora / Presidente do Conselho Diretivo do …" (no
"Ao/À" before a person in PT usage; "À Direção-Geral de …" before an institution). "Prezado(a)" is more typical
of Brazil; semi-formal PT e-mails usually open with "Caro/Cara".

**Requerimento** — the Código do Procedimento Administrativo (Decreto-Lei n.º 4/2015, art. 102.º) requires a
written initial request to contain: (a) the administrative body it is addressed to; (b) the applicant's name and
domicile and, if possible, civil and tax identification numbers; (c) the facts and, where possible, the legal
grounds; (d) the request, in clear and precise terms; (e) date and signature; (f) the address for notifications;
(g) phone or e-mail for notifications.
```text
Exmo(a). Senhor(a) <cargo> do/da <órgão>

<Nome>, titular do cartão de cidadão n.º <…>, contribuinte n.º <…>, residente em <morada>, vem requerer a
V. Ex.ª <pedido claro e preciso>, ao abrigo do <artigo X.º do Decreto-Lei n.º …/…>, com os seguintes fundamentos:
1.º <facto>
2.º <facto>
Junta: <documentos>.
Pede deferimento.
<Local>, <dia> de <mês> de <ano>
<Assinatura>
Contactos para notificações: <morada / e-mail / telefone>
```
Guardrails: include only the personal data the procedure needs; never cite a law, article or deadline you have not
checked in the current consolidated text on diariodarepublica.pt (or the service's official page); flag deadlines
and recommend confirming legal effects with the service or a lawyer — drafting is not legal advice.

## 6. Translating from English
Process: understand → translate the meaning → rewrite in natural Portuguese order → terminology pass (§2, IATE,
Microsoft Terminology) → typography pass (§4) → read aloud.
| English | Trap | Use |
|---|---|---|
| actually | *atualmente* = currently | na verdade, de facto |
| eventually | *eventualmente* = possibly | acabar por, por fim, mais tarde |
| pretend | *pretender* = intend | fingir |
| realize | *realizar* = carry out | aperceber-se, perceber |
| assume (that) | *assumir* = take on | supor, partir do princípio |
| attend (a class, a meeting) | *atender* = serve, answer (the phone) | assistir a, frequentar, estar presente em |
| assist | *assistir (a)* = watch, attend | ajudar, apoiar |
| library | *livraria* = bookshop | biblioteca |
| comprehensive | *compreensivo* = understanding | abrangente, exaustivo |
| consistent | *consistente* = solid, firm | coerente, uniforme |
| sensible | *sensível* = sensitive | sensato |
| severe (disease) | *severo* = harsh | grave |
| resume | *resumir* = summarize | retomar |
| data | *data* = date | dados |
| parents | *parentes* = relatives | pais |
| college | *colégio* = (private) school | ensino superior, faculdade |
| constipated | *constipado* = has a cold | com prisão de ventre |
| argument (quarrel) | *argumento* = reasoning | discussão |
| evidence | *evidência* = obviousness (but *medicina baseada na evidência* is established) | provas, dados, indícios |
| introduce (a person) | *introduzir* = insert | apresentar |
| apply for | calque *aplicar para* | candidatar-se a |
| address (an issue) | calque *endereçar* | tratar, resolver, abordar |
| billion / trillion | short vs long scale | mil milhões / bilião |
Maths and science: demonstração (proof), lema, corolário, conjetura, hipótese, espaço vetorial, desvio-padrão,
variável aleatória, valor esperado; decimal comma in prose and tables. Prefer established Portuguese terms
(desempenho for performance, prazo for deadline) unless the field keeps the English one.

## 7. Tone and concision
- Plain language (Livro de Estilo, justica.gov.pt): sentences ≤ 35 words, paragraphs ~6 lines, active voice,
  simple words ("fazer" not "efetuar", "dizer" not "verbalizar"), explain jargon, avoid Latin tags, address the
  reader directly ("Registe o seu terreno").
- Cut bureaucratic filler: "vem por este meio" → delete; "no sentido de" → "para"; "a nível de" → "em", "quanto a";
  "proceder à análise" → "analisar"; "efetuar o pagamento" → "pagar"; "encontra-se em anexo" → "junto".
- Portuguese formal prose is less effusive than Brazilian; one courtesy formula at the end is enough.

## 8. Proofreading checklist
- [ ] Variant pt-PT throughout; manual pass for BR vocabulary and BR spellings (table §2; acute vs circumflex).
- [ ] One spelling norm (AO1990 unless told otherwise); doubtful words checked in VOP/Priberam.
- [ ] Clitics: enclisis by default, proclisis after triggers, no sentence-initial clitic.
- [ ] "estar a + infinitivo"; no *você* in writing; one consistent form of address.
- [ ] « » quotes; spaced travessões; ordinals 1.º/2.ª with º/ª; months in lower case.
- [ ] Numbers: decimal comma, space grouping, currency after the amount, *mil milhões*, dates and times.
- [ ] False friends and calques (§6) checked.
- [ ] Formal texts: addressee, request stated clearly, legal references verified, attachments listed, closing.
- [ ] Read aloud: natural order, no calques, no repeated words.

## Verify
- LanguageTool with `pt-PT` flags pre-AO spellings (e.g. *actualmente*) but in a test let BR vocabulary through
  (*arquivo*, *tela*, *download*) — it does not replace the manual pass. Public API:
  `curl -s -d language=pt-PT --data-urlencode "text@texto.txt" https://api.languagetool.org/v2/check`
  (rate-limited; never send personal or confidential text to it — run a local LanguageTool server instead).
- Grep for BR markers: `grep -n -w -E 'tela|arquivo|usuário|celular|baixar|salvar|excluir|equipe|registro|controle|ônibus|trem|você' file`
  and review each hit (some are legitimate in context).
- Spot-check numbers/dates/currency with a regex for `[0-9]\.[0-9]{3}` (point as thousands separator) and `€ ?[0-9]` (symbol before amount).

## Deliverables / Report
- The final text in pt-PT, in the requested format.
- For translations: a short note with the terminology table (EN → pt-PT, source consulted), choices made (spelling
  norm, form of address), unresolved ambiguities and items for the client to confirm.
- For formal letters and requerimentos: the text, the list of attachments, and deadlines or legal references
  that still need the user's confirmation.
