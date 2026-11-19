from flask import Flask, render_template, request, redirect, url_for, session, flash
import os
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__, template_folder='.', static_folder='.', static_url_path='')
app.secret_key = "techstore_secret_key"

# Inicialização do Firebase Firestore
if not firebase_admin._apps:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ---------------------------------------------------------
# ROTAS DE AUTENTICAÇÃO E RBAC
# ---------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        senha = request.form["senha"]
        
        # Validação simples contra contas padrão no Firebase/Sessão
        if email == "gerente@techstore.com" and senha == "123456":
            session["usuario_id"] = "gerente_id"
            session["nome"] = "Gerente TechStore"
            session["perfil"] = "GERENTE"
            flash("Login realizado com sucesso!", "success")
            return redirect(url_for("index"))
        elif email == "operador@techstore.com" and senha == "123456":
            session["usuario_id"] = "operador_id"
            session["nome"] = "Operador WMS"
            session["perfil"] = "OPERADOR"
            flash("Login realizado com sucesso!", "success")
            return redirect(url_for("index"))
        else:
            flash("E-mail ou senha incorretos.", "danger")
            
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Sessão encerrada com sucesso.", "success")
    return redirect(url_for("login"))

# ---------------------------------------------------------
# ROTA PRINCIPAL (CATÁLOGO)
# ---------------------------------------------------------
@app.route("/")
def index():
    if "usuario_id" not in session:
        return redirect(url_for("login"))
        
    # Busca todos os produtos salvos na coleção do Firestore
    produtos_ref = db.collection("produtos").stream()
    produtos = []
    for doc in produtos_ref:
        p = doc.to_dict()
        p["id_produto"] = doc.id  # ID gerado pelo Firebase
        # Valores padrão para manter compatibilidade com o HTML existente
        p.setdefault("categoria", "Geral")
        p.setdefault("fornecedor", "Padrão")
        produtos.append(p)
        
    return render_template("index.html", produtos=produtos)

# ---------------------------------------------------------
# CADASTRAR NOVO PRODUTO
# ---------------------------------------------------------
@app.route("/produto/novo", methods=["GET", "POST"])
def novo_produto():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        try:
            sku = request.form["sku"].strip()
            nome_comercial = request.form["nome_comercial"].strip()
            fabricante = request.form["fabricante"].strip()
            classificacao = request.form["classificacao"]
            especificacao_tecnica = request.form.get("especificacao_tecnica", "")
            modalidade_licenciamento = request.form.get("modalidade_licenciamento", "N/A")
            preco_venda = float(request.form["preco_venda"])
            quantidade_estoque = int(request.form["quantidade_estoque"])
            localizacao = request.form["localizacao"].strip()
            categoria = request.form.get("id_categoria", "Geral")
            fornecedor = request.form.get("id_fornecedor", "Padrão")

            # Salva o documento diretamente no Firestore
            db.collection("produtos").add({
                "sku": sku,
                "nome_comercial": nome_comercial,
                "fabricante": fabricante,
                "classificacao": classificacao,
                "especificacao_tecnica": especificacao_tecnica,
                "modalidade_licenciamento": modalidade_licenciamento,
                "preco_venda": preco_venda,
                "quantidade_estoque": quantidade_estoque,
                "localizacao": localizacao,
                "categoria": categoria,
                "fornecedor": fornecedor
            })
            
            flash("Ativo cadastrado com sucesso no Firebase!", "success")
            return redirect(url_for("index"))
        except Exception as e:
            flash(f"Erro ao inserir no Firebase: {e}", "danger")
            return redirect(url_for("novo_produto"))

    # Listas simuladas para os selects do formulário HTML
    categorias = [{"id_categoria": "Hardware", "nome": "Hardware"}, {"id_categoria": "Software", "nome": "Software"}]
    fornecedores = [{"id_fornecedor": "Principal", "razao_social": "Fornecedor Principal Ltda"}]
    
    return render_template("form_produto.html", categorias=categorias, fornecedores=fornecedores)

# ---------------------------------------------------------
# MOVIMENTAÇÃO DE ESTOQUE
# ---------------------------------------------------------
@app.route('/movimentacao', methods=['GET', 'POST'])
def movimentacao():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    if request.method == 'POST':
        id_produto = request.form["id_produto"]
        tipo_operacao = request.form["tipo_operacao"]
        quantidade = int(request.form["quantidade"])
        justificativa = request.form["justificativa"].strip()

        prod_ref = db.collection("produtos").document(id_produto)
        doc = prod_ref.get()
        
        if not doc.exists:
            flash("Produto não encontrado.", "danger")
            return redirect(url_for("movimentacao"))

        dados = doc.to_dict()
        saldo_atual = int(dados.get("quantidade_estoque", 0))

        if tipo_operacao == "Saída" and quantidade > saldo_atual:
            flash(f"Operação Bloqueada: Saldo insuficiente. Disponível: {saldo_atual} unidades.", "danger")
            return redirect(url_for("movimentacao"))

        novo_saldo = saldo_atual + quantidade if tipo_operacao == "Entrada" else saldo_atual - quantidade

        try:
            # Atualiza o estoque e registra o log na nuvem
            prod_ref.update({"quantidade_estoque": novo_saldo})
            db.collection("movimentacoes").add({
                "id_produto": id_produto,
                "tipo_operacao": tipo_operacao,
                "quantidade": quantidade,
                "justificativa": justificativa,
                "data": firestore.SERVER_TIMESTAMP
            })
            flash("Movimentação consolidada com sucesso no Firebase!", "success")
            return redirect(url_for("index"))
        except Exception as e:
            flash(f"Erro ao processar movimentação: {e}", "danger")

    produtos_ref = db.collection("produtos").stream()
    produtos = [{"id_produto": d.id, **d.to_dict()} for d in produtos_ref]
    return render_template("form_movimentacao.html", produtos=produtos)

# ---------------------------------------------------------
# CHECKOUT TRANSACIONAL
# ---------------------------------------------------------
@app.route("/venda/checkout", methods=["GET", "POST"])
def checkout():
    if "usuario_id" not in session:
        return redirect(url_for("login"))
    
    if request.method == "POST":
        cliente_nome = request.form["cliente_nome"]
        cliente_documento = request.form["cliente_documento"]
        forma_pagamento = request.form["forma_pagamento"]
        
        produtos_ids = request.form.getlist("produto_id[]")
        quantidades = request.form.getlist("quantidade[]")
        usuario_id = session["usuario_id"]
        
        try:
            valor_total_venda = 0
            itens_a_faturar = []
            
            for i in range(len(produtos_ids)):
                p_id = produtos_ids[i]
                qtd = int(quantidades[i])
                
                prod_ref = db.collection("produtos").document(p_id)
                doc = prod_ref.get()
                
                if not doc.exists:
                    raise Exception(f"Produto ID {p_id} não encontrado!")
                
                prod_data = doc.to_dict()
                estoque_atual = int(prod_data.get("quantidade_estoque", 0))
                
                if estoque_atual < qtd:
                    raise Exception(f"Estoque insuficiente para o produto {prod_data.get('nome_comercial', '')}!")
                
                preco_unitario = float(prod_data.get("preco_venda", 0))
                subtotal = preco_unitario * qtd
                valor_total_venda += subtotal
                
                itens_a_faturar.append({
                    "produto_id": p_id,
                    "quantidade": qtd,
                    "preco_unitario": preco_unitario,
                    "subtotal": subtotal,
                    "estoque_atual": estoque_atual,
                    "nome": prod_data.get("nome_comercial", "")
                })
            
            numero_pedido = f"PED-2026-{abs(hash(cliente_documento + str(valor_total_venda))) % 10000:04d}"
            
            # Grava a venda principal no Firestore
            venda_ref = db.collection("vendas").document()
            venda_ref.set({
                "numero_pedido": numero_pedido,
                "cliente_nome": cliente_nome,
                "cliente_documento": cliente_documento,
                "forma_pagamento": forma_pagamento,
                "valor_total": valor_total_venda,
                "status_venda": "CONCLUIDA",
                "usuario_id": usuario_id,
                "data_hora": firestore.SERVER_TIMESTAMP
            })
            
            # Processa os itens e baixa o estoque de cada produto
            for item in itens_a_faturar:
                db.collection("itens_venda").add({
                    "venda_id": venda_ref.id,
                    "produto_id": item["produto_id"],
                    "quantidade_vendida": item["quantidade"],
                    "preco_unitario_praticado": item["preco_unitario"],
                    "subtotal_item": item["subtotal"]
                })
                
                novo_estoque = item["estoque_atual"] - item["quantidade"]
                db.collection("produtos").document(item["produto_id"]).update({"quantidade_estoque": novo_estoque})
            
            flash(f"Venda {numero_pedido} realizada com sucesso na nuvem!", "success")
            return redirect(url_for("recibo", venda_id=venda_ref.id))
            
        except Exception as e:
            flash(f"Erro na transação (Operação Abortada): {str(e)}", "danger")
            return redirect(url_for("checkout"))
            
    produtos_ref = db.collection("produtos").where("quantidade_estoque", ">", 0).stream()
    produtos = []
    for doc in produtos_ref:
        d = doc.to_dict()
        produtos.append((doc.id, d.get("nome_comercial"), d.get("preco_venda"), d.get("quantidade_estoque")))
        
    return render_template("checkout.html", produtos=produtos)

@app.route("/venda/recibo", defaults={"venda_id": ""})
@app.route("/venda/recibo/<string:venda_id>")
def recibo(venda_id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))
        
    if not venda_id or venda_id == "0":
        # Pega a última venda registrada
        vendas_stream = db.collection("vendas").order_by("data_hora", direction=firestore.Query.DESCENDING).limit(1).stream()
        venda_doc = next(vendas_stream, None)
        if not venda_doc:
            flash("Comprovante não encontrado.", "danger")
            return redirect(url_for("index"))
        venda_id = venda_doc.id
        venda = venda_doc.to_dict()
        venda["id_venda"] = venda_id
    else:
        venda_doc = db.collection("vendas").document(venda_id).get()
        if not venda_doc.exists:
            flash("Comprovante não encontrado.", "danger")
            return redirect(url_for("index"))
        venda = venda_doc.to_dict()
        venda["id_venda"] = venda_id
        
    venda.setdefault("operador", session.get("nome", "Operador"))
    
    # Busca os itens da venda
    itens_stream = db.collection("itens_venda").where("venda_id", "==", venda_id).stream()
    itens = []
    for item_doc in itens_stream:
        i = item_doc.to_dict()
        # Busca o nome do produto correspondente
        p_doc = db.collection("produtos").document(i["produto_id"]).get()
        nome_prod = p_doc.to_dict().get("nome_comercial", "Produto") if p_doc.exists else "Produto"
        itens.append((nome_prod, i["quantidade_vendida"], i["preco_unitario_praticado"], i["subtotal_item"]))
    
    return render_template("recibo.html", venda=venda, itens=itens)

# ---------------------------------------------------------
# EXCLUSÃO DE ATIVO (COM SEGURANÇA RBAC)
# ---------------------------------------------------------
@app.route('/produto/excluir-selecionado', methods=['POST'])
def excluir_selecionado():
    if "usuario_id" not in session:
        return redirect(url_for("login"))
        
    if session.get('perfil') != 'GERENTE':
        flash("Acesso negado. Apenas gerentes podem excluir ativos.", "danger")
        return redirect(url_for('index'))
        
    id_produto = request.form.get("id_produto")
    if not id_produto:
        flash("Nenhum produto selecionado.", "danger")
        return redirect(url_for('index'))
        
    try:
        db.collection("produtos").document(id_produto).delete()
        flash("Ativo excluído com sucesso do Firebase!", "success")
    except Exception as e:
        flash(f"Erro ao excluir ativo: {e}", "danger")
        
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)