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

Escrevi o tratamento e as regras diretamente no notebook. Para o Nível 2 isso
significa extrair as funções para um módulo importável, trabalho que teria sido
evitado se eu tivesse começado por src/pipeline.py, com o notebook importando e
narrando

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

### Sem cache de respostas

Cada execução completa do notebook refaz três chamadas à API. Numa cota gratuita
com limite por minuto, isso é desperdício e ponto de falha

## Nivel 2, o que faria

Não implementado no momento desta escrita. Plano:

**Regras em escala.** Extrair as funções do notebook para um módulo importável e
aplicá-las a dados_nivel_2.json. Os quatro problemas de qualidade são os mesmos,
em maior número, o tratamento é idêntico. O top 10 sai de um groupby por
cliente contando sinalizações, com volume total como desempate

**Ferramentas.** historico_cliente, operacoes_do_dia e perfil_canal como
funções puras sobre o DataFrame já tratado, cada uma devolvendo dicionário
serializável. Elas não decidem nada, apenas recortam e agregam

**Agente.** O ponto que separa agente de script é a decisão de *quais* ferramentas
chamar. Faria com tool calling nativo do SDK: o modelo recebe o dossiê inicial e
as descrições das ferramentas, e decide o que consultar. Um cliente sinalizado por
fracionamento leva naturalmente a operacoes_do_dia na data do alerta; um cliente
sinalizado por valor atípico leva a historico_cliente para contextualizar a
mediana. Registraria quais ferramentas cada caso acionou, é a evidência de que
houve decisão, e não roteiro fixo

**Lote e custo.** Cache em disco indexado pelo hash do dossiê, para reexecutar o
notebook sem repetir chamadas. Custo e latência por chamada num DataFrame,
agregados ao final

**Confronto.** Critério: cliente sinalizado pelas duas regras deveria sair como
"alto"; por uma, "medio"; por nenhuma, "baixo". Reportaria a taxa de concordância,
mas o valor está nas divergências. Como as regras são deliberadamente simples,
espero falsos positivos, e um agente que discorde com justificativa ancorada nos
dados pode estar certo. Classificaria cada divergência em "agente certo", "regra
certa" ou "indeterminado", com uma frase de análise em cada

**Como validaria.** Casos-teste construídos à mão com resultado conhecido:
um fracionamento clássico, um caso na borda do limiar, um cliente de alto volume
sem padrão suspeito. Se o agente classificar os três corretamente, há evidência de
que ele interpreta em vez de repetir a regra

## Nivel 3, trilha escolhida

**Trilha B, servidor MCP local.** Não implementado

Escolhi essa trilha porque as ferramentas do Nível 2 já são funções puras e sem
estado, o que as torna diretamente expostáveis. O trabalho seria de protocolo, não
de lógica

Exporia as três funções via stdio, com schema de entrada declarado por ferramenta,
e faria o agente consumi-las por MCP em vez de import direto. O ganho concreto:
as mesmas ferramentas passariam a ser utilizáveis por qualquer cliente MCP sem
acoplamento ao meu código, outro agente, ou um analista usando um cliente MCP
diretamente

**Como validaria:** subir o servidor, listar as ferramentas pelo protocolo,
chamar cada uma com um cliente_id conhecido e conferir que a resposta é idêntica
à da chamada por import direto. Se divergir, o problema está na serialização
