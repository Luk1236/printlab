import io
import re

T = {
 'de':  ['Preisliste', 'Materialname'],
 'en':  ['Price list', 'Material name'],
 'es':  ['Lista de precios', 'Nombre del material'],
 'fr':  ['Liste des prix', 'Nom du matériau'],
 'it':  ['Listino prezzi', 'Nome materiale'],
 'ja':  ['価格表', 'マテリアル名'],
 'ko':  ['가격표', '재료명'],
 'nl':  ['Prijslijst', 'Materiaalnaam'],
 'pt-BR': ['Lista de preços', 'Nome do material'],
 'ru':  ['Прейскурант', 'Название материала'],
 'sv':  ['Prislista', 'Materialnamn'],
 'tr':  ['Fiyat listesi', 'Malzeme adı'],
 'uk':  ['Прайс-лист', 'Назва матеріалу'],
 'zh-CN': ['价格表', '材料名'],
 'zh-TW': ['價格表', '材料名'],
}
keys = ['priceList', 'materialName']

for loc, vals in T.items():
    p = f'src/i18n/locales/{loc}.ts'
    src = io.open(p, encoding='utf-8').read()
    if 'priceList:' in src:
        continue
    m = re.search(r'(jobRulesThreshold[^\n]*\n)', src)
    if not m:
        print(loc, 'no anchor')
        continue
    insert = ''.join(f"      {k}: '{vals[i].replace(chr(39), chr(92) + chr(39))}',\n" for i, k in enumerate(keys))
    src = src.replace(m.group(1), m.group(1) + insert)
    io.open(p, 'w', encoding='utf-8').write(src)
    print(loc, 'ok')