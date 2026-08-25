# Uso de IA

## Ferramentas

Usei o **Claude Code** (Anthropic) durante todo o desenvolvimento, dentro do VSCode.

## Para quê

 Aprendi muito com esse case e com as explicações da IA, pois eu não dominava tudo, seja código ou conceitos a respeito das resoluções do case, por conta disso usei a IA, para me aprofundar e aprender mais! agora consigo explicar o case, falar dos problemas, das soluções e das escolhas. Desde ja agradeço pela oportunidade e pelo case, eu aprendi muito nesse tempo  

 Os usos concretos foram três:

Aprender mecânica de pandas que eu não dominava

Revisar minhas justificativas

Discutir decisões sem resposta única

As decisões finais foram tomadas por mim, mas segui consultando a IA para confirmar, ver se é a melhor resposta, se esta correto, partes do código que eu não dominava ou não lembrava

## Onde a IA me levou para o caminho errado

**Modelo que não existe.** A sugestão inicial de modelo foi
llama-3.3-70b-versatile, apresentada como padrão da Groq. Ao listar os modelos
disponíveis na minha conta, ele não estava lá — nenhum Llama de uso geral estava.
Acabei usando openai/gpt-oss-120b. Aprendi a conferir ID de modelo no console do
provedor em vez de aceitar de memória de uma LLM, que tem data de corte e não sabe
o que foi descontinuado depois

**Número afirmado sem cálculo.** Ao conferir minhas agregações, a IA afirmou que o
volume total da base era R$ 189.100. O valor que estava na minha tela,
era R$ 265.500. Foi um número inventado com aparência de verificação, tipo de
erro mais perigoso, porque vem com tom de confiança 

**Código com problema de tipo.** O código sugerido para a conversão cambial criava
a coluna valor_brl como inteiro e depois gravava um valor decimal nela, gerando
FutureWarning do pandas na saída. Só apareceu ao executar; corrigi com
.astype(float) na criação da coluna

**Cache sem chave de modelo.** O cache de respostas que a IA sugeriu era indexado
apenas pelo dossiê do cliente, sem incluir o modelo. Quando troquei do 120b para
o 20b, resultados do modelo antigo voltavam do cache como se fossem do novo, e
eu não teria como saber qual modelo produziu qual parecer na hora de declarar isso
no ENTREGA.yaml. Percebi ao conferir e corrigi incluindo o modelo na chave e no
registro de cada parecer


