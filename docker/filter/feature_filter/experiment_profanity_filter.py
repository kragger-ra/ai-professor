# Python 3.10.10
# Python 3.10.10


from profanity_filter import ProfanityFilter

# pf = ProfanityFilter(languages=['ru', 'en'])

pf = ProfanityFilter(languages=["ru"])

print(pf.is_clean("Это прекрасно, очень хорошо"))
