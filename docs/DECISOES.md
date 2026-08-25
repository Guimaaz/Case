# Decisões

## Trade-offs

### Manter a operação sem data em vez de descartá-la

OP-0017 tem cliente, valor, canal e tipo válidos, só a data se perdeu na origem
(a própria observacao registra "data nao capturada pelo sistema")

Considerei três caminhos. Imputar uma data foi descartado de saída: inventar um
fato num relatório de PLD é indefensável, e a data é justamente o eixo da regra de
fracionamento. Entre descartar a linha e mantê-la, o número decidiu, CLI-A-5
tem exatamente 4 operações, e a Regra 2 só avalia clientes com 4 ou mais. Remover
a linha o reduziria a 3 e o tiraria inteiro do escopo de uma regra que sequer usa
data

O defeito invalida a operação em um lugar só, então a exclusão vale só nesse
lugar. Na prática não custou código: groupby ignora chaves nulas por padrão

### Coluna valor_brl nova, preservando valor

Poderia ter sobrescrito valor com o montante convertido. Preferi criar coluna
separada porque, em compliance, é preciso poder mostrar o valor como veio da
origem ao lado do valor usado no cálculo. O custo é uma coluna a mais; o ganho é
rastreabilidade

### drop_duplicates() sem subset

A alternativa, subset=["id"], removeria qualquer id repetido independente do
conteúdo. É mais agressiva e perigosa: se dois registros tivessem o mesmo id e
valores diferentes, ela apagaria um às cegas, e não haveria como saber qual era o
correto. A forma sem subset só age quando a linha inteira coincide, verifiquei
que era o caso antes de aplicar

### "Atinge R$ 20.000" lido como < 20.000

O enunciado diz "nenhuma operação isolada atinge R$ 20.000". Interpretei que
uma operação de exatamente R$ 20.000 descaracteriza o padrão: quem consegue fazer
a operação no valor cheio não está fracionando. Por isso a condição para sinalizar
é maior_operacao < 20.000, e não <=

### Flag por operação, não por cliente

O enunciado fala em sinalizar o cliente. Gravei a flag em cada operação do grupo
porque o analista precisa saber *quais* operações compuseram o padrão, não apenas
que o cliente foi sinalizado. A lista de clientes continua acessível com um
unique(); o caminho inverso, do cliente para as operações, não seria
recuperável

### Mediana e não média na Regra 2

A mediana é resistente a outliers. Usando média, uma operação muito alta puxaria
a referência para cima e elevaria o próprio limiar que deveria detectá-la. Com
mediana, a operação anômala não move a régua contra a qual é medida

### Lógica no notebook, extração adiada

Escrevi o tratamento e as regras diretamente no notebook

**O que aconteceu na prática:** extraí as funções para nivel_2/pipeline.py no
início do Nível 2, e o custo foi baixo porque a lógica já estava correta e testada.
Ainda assim, o notebook do Nível 1 mantém sua própria cópia do código, as duas
implementações podem divergir se uma for alterada. Começar pelo módulo, com o
notebook importando dele, teria evitado essa duplicação


**O que faria diferente desde o começo:** definir de saída funções puras
(carregar, limpar, normalizar_brl, regra_fracionamento,
regra_valor_atipico) recebendo e devolvendo DataFrame, num módulo único. O
notebook do Nível 1 importaria e mostraria o raciocínio em markdown; o Nível 2
importaria as mesmas funções apontando para a base maior. A reutilização deixaria
de ser cópia e passaria a ser garantia, se as regras forem as mesmas, os
resultados são comparáveis por construção

### Pydantic em vez de validação manual

Validar com ifs daria no mesmo para quatro campos. Optei pelo Pydantic porque o
schema é declarativo e serve simultaneamente de documentação do contrato. O
benefício apareceu na prática: a v1 do prompt devolveu "Alto" com maiúscula, o
Literal reprovou, e o erro foi contido no registro em vez de contaminar o
pipeline

## Limitações

### Limiares fixos e frágeis na borda

CLI-A-3 fez três operações no mesmo dia, todas abaixo de R$ 20.000, somando
R$ 48.500. Falha na Regra 1 por R$ 1.500. Um cliente que fracione em R$ 49.000
passa livre, indefinidamente. Limiar absoluto é fácil de auditar e fácil de
contornar

### A regra não mede proximidade do limiar

O indício mais forte do caso positivo, os valores de R$ 18.100, R$ 17.300 e
R$ 18.800 concentrados 6% abaixo de R$ 20.000, **não é capturado por nenhuma das
duas regras**. A Regra 1 apenas verifica que nenhuma operação atinge o limite; ela
não observa o quão perto elas chegam sistematicamente. Um cliente cujas operações
se aglomeram logo abaixo de um patamar de reporte é qualitativamente diferente de
um cujos valores se distribuem de forma dispersa, e hoje as duas situações são
indistinguíveis para o sistema

### Janela de um único dia

A Regra 1 agrupa por (cliente, data). Fracionamento distribuído ao longo de três
dias, o padrão mais comum na prática, é invisível para ela

### A Regra 2 é cega a valor absoluto

Ela detecta desvio do padrão próprio do cliente, não magnitude. Um cliente cujas
operações sejam todas altas e homogêneas nunca é sinalizado, por maiores que
sejam. As duas regras são complementares por isso, e ainda assim deixam vãos

### Taxa de câmbio única

O enunciado fornece uma taxa fixa e instrui a usá-la. Com dados reais, a conversão
precisaria da cotação da data de cada operação; uma taxa única distorce
comparações entre operações distantes no tempo

### Base pequena

20 operações e 6 clientes não sustentam nenhuma inferência estatística. Os
resultados do Nível 1 são demonstração de mecanismo, não evidência

### A LLM não é determinística

Mesmo com temperature=0, execuções distintas podem divergir. As saídas
commitadas são de uma execução específica. Em produção, o parecer precisaria ser
versionado junto com o modelo, o prompt e o dossiê que o originou

### O cache não expira

Implementei cache em disco no Nível 2, indexado por (modelo, dossiê). Ele resolve o
custo de reexecução, mas não tem invalidação: se o prompt mudar, a chave continua a
mesma e o resultado antigo volta silenciosamente. Em uso real, a chave precisaria
incluir também a versão do prompt


## Confronto regra x agente

**Critério.** O nível esperado deriva de quantas regras o cliente acionou: duas
regras → "alto", uma → "medio", nenhuma → "baixo". Escolhi um critério simples de
propósito, espelhando a simplicidade das próprias regras

**Resultado: 80% de concordância** (8/10), com duas divergências, ambas na mesma
direção, o agente escalou de "medio" para "alto"

### A primeira limitação é do critério, não do agente

Os 10 clientes do top acionaram exatamente uma regra cada. Isso significa que
o critério previu "medio" para todos os 10, e a taxa de 80% mede apenas quantas
vezes o agente também disse "medio". O critério não discrimina nada nesta amostra:
ele nunca produz "alto" nem "baixo" aqui. A métrica, isolada, não diz quase nada

### As duas divergências

CLI-017 e CLI-002 foram sinalizados por fracionamento, consultaram
operacoes_do_dia, viram o detalhe e escalaram

Considero o agente mais certo que a regra nos dois casos, por um motivo que o
critério ignora: ele conta regras, mas não pesa qual regra. Fracionamento e
valor atípico não são equivalentes. Um valor atípico pode ter explicação trivial, a venda de um bem, um recebimento sazonal. Já 4 operações no mesmo dia, todas logo
abaixo de um limiar de reporte, é um padrão que exige intenção. Não se fraciona
por acaso

O agente enxergou isso porque foi olhar o dia; a regra não enxerga porque só
pergunta "acionou ou não"

### Mas o agente acertou pelo motivo parcialmente errado

A justificativa do CLI-002 afirma que "o uso de canais eletrônicos (Pix e TED)
facilita a movimentação rápida e pode reduzir a rastreabilidade". Isso está
invertido: Pix e TED são mais rastreáveis que espécie, e o próprio dado
disponível permitiria notar isso. O modelo produziu um indício plausível ao ouvido
mas incorreto no mérito

A conclusão sobreviveu porque o argumento principal (concentração de 60% do
volume em um único dia) se sustenta sozinho. Mas o episódio mostra por que o
parecer da LLM precisa passar por analista humano: o texto é convincente
independentemente de estar certo, e uma red flag errada num relatório de PLD pode
direcionar uma investigação para o lado errado

### O que eu mudaria no critério

Pesar as regras em vez de contá-las: fracionamento sozinho já indicaria "alto",
por implicar intenção, enquanto valor atípico sozinho ficaria em "medio". Com esse
critério a concordância neste lote subiria para 100%, mas isso seria ajustar a
régua ao resultado observado, e eu preciso de mais casos antes de afirmar que a
regra nova é melhor e não apenas ajustada a esta amostra



## O que faria com mais tempo

**Fracionamento em janela móvel.** A Regra 1 olha um único dia. Trocaria por uma
janela deslizante de N dias, com N configurável, e reportaria a janela que
disparou. O padrão real raramente se concentra em 24 horas

**Regra de proximidade de limiar.** O indício mais forte que encontrei nos dois
lotes, valores agrupados logo abaixo de R$ 20.000, não é capturado por nenhuma
regra atual. Mediria a distância relativa de cada operação ao limiar e sinalizaria
concentração anormal na faixa de 85% a 99% dele. Validaria comparando a
distribuição dos clientes sinalizados contra a dos demais: se a diferença não for
visível num histograma, a regra não presta

**Peso por tipo de regra no confronto.** O critério atual conta regras acionadas
sem distinguir qual. Fracionamento implica intenção; valor atípico pode ter
explicação trivial. Testaria um critério ponderado, mas em amostra separada da que
usei para observar as divergências, ajustar a régua depois de ver o resultado é
sobreajuste, não melhoria

**Chamadas em paralelo.** O lote é sequencial e leva 46s por cliente. Com
asyncio e controle de taxa, os 30 clientes da base rodariam em uma fração do
tempo. Não fiz porque a camada gratuita limita requisições por minuto e o ganho
seria anulado

**Avaliação do agente com casos-teste.** Hoje eu observo que ele escolhe
ferramentas coerentes, mas não meço isso. Construiria um conjunto pequeno de casos
com resultado conhecido, um fracionamento clássico, um caso na borda do limiar,
um cliente de alto volume sem padrão suspeito, e verificaria se ele classifica os
três corretamente e consulta as ferramentas esperadas. Sem isso, "o agente decide
bem" é impressão, não evidência

**Painel para o analista.** O parecer hoje sai em JSON. Uma interface listando os
clientes sinalizados, com o parecer e as operações que o motivaram lado a lado,
seria o que de fato colocaria isso na mesa de triagem


## Nivel 3, trilha escolhida

**Implementei a trilha A - fluxo multiagente.** Código em nivel_3/fluxo.py,
diagrama em [ARQUITETURA.md](ARQUITETURA.md)

Havia planejado a trilha B. Ao avaliar o tempo disponível, optei pela A por
reaproveitar integralmente as ferramentas e o loop de tool calling do Nível 2, o
trabalho ficou restrito a encadear três papéis sobre um estado compartilhado, sem
introduzir protocolo nem biblioteca nova. A B exigiria aprender o SDK do MCP e
depurar comunicação por stdio, o que não cabia com segurança na janela disponível

Resultado: os 10 clientes do top passaram pelo fluxo, com o Triador definindo
prioridade e focos, o Investigador consultando de 2 a 4 ferramentas conforme o
caso, e os 10 pareceres validando no schema. A condição de parada foi verificada
com o CLI-012, arquivado pelo Triador sem acionar os demais papéis

Uma limitação honesta: nos 10 do top, o Triador encaminhou todos. Isso é coerente, são os clientes mais sinalizados da base, mas significa que a seletividade do
Triador não foi exercitada em escala. Para medir isso de fato, eu rodaria o fluxo
sobre os 30 clientes e verificaria se a taxa de arquivamento acompanha a ausência
de flags

**A trilha B fica como próximo passo.** O plano original segue abaixo

### Trilha B, servidor MCP local (planejado)

Escolhi originalmente essa trilha porque as ferramentas do Nível 2 já são funções
puras e sem estado, o que as torna diretamente expostáveis. O trabalho seria de
protocolo, não de lógica

Exporia historico_cliente, operacoes_do_dia e perfil_canal via stdio, com
schema de entrada declarado por ferramenta, e faria o agente consumi-las por MCP
em vez de import direto. O ganho concreto: as mesmas ferramentas passariam a ser
utilizáveis por qualquer cliente MCP sem acoplamento ao meu código, outro agente,
ou um analista usando um cliente MCP diretamente

O ponto de atenção seria o estado. Hoje as ferramentas guardam a base num módulo
(tools.usar_base(df)), o que funciona porque tudo roda no mesmo processo. Como
servidor, a base precisaria ser carregada na inicialização do processo do servidor,
e o ciclo de vida dela passaria a ser responsabilidade dele

**Como validaria:** subir o servidor, listar as ferramentas pelo protocolo, chamar
cada uma com um cliente_id conhecido e conferir que a resposta é byte a byte
idêntica à da chamada por import direto. Se divergir, o problema está na
serialização, que é exatamente o risco de trocar chamada de função por protocolo



