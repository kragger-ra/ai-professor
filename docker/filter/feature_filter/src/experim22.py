import pymorphy2

morph = pymorphy2.MorphAnalyzer()

word = "людьми"
parsed_word = morph.parse(word)
# print(parsed_word)
# [Parse(word='людьми', tag=OpencorporaTag('NOUN,anim,masc plur,ablt'),
# normal_form='человек', score=1.0, methods_stack=((DictionaryAnalyzer(), 'людьми', 3166, 12),))]


from .main import TextModeration

moderation = TextModeration(["спам", "мошенничество"], ["нецензурная лексика"])

sentence = "Привет вы пойдете сегодня на рыбалку, а na ribalky?"
tr_res = moderation.transliterate_sentence(sentence)

print(tr_res)
