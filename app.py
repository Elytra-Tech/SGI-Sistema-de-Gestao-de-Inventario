import os
import json
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

app = Flask(__name__, template_folder='.', static_folder='.', static_url_path='')
app.secret_key = "techstore_secret_key"

# ---------------------------------------------------------
# INICIALIZAÇÃO DO FIREBASE ROBUSTA PARA VERCEL
# ---------------------------------------------------------
if not firebase_admin._apps:
    firebase_credentials_str = os.environ.get("FIREBASE_CREDENTIALS")
    if firebase_credentials_str:
        try:
            cred_dict = json.loads(firebase_credentials_str)
        except json.JSONDecodeError:
            cred_dict = json.loads(firebase_credentials_str.replace('\n', '\\n'))
        cred = credentials.Certificate(cred_dict)
    else:
        cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ---------------------------------------------------------
# DECORADOR DE CONTROLE DE ACESSO (RBAC)
# ---------------------------------------------------------
def gerente_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login"))
        if session.get("perfil") != "GERENTE":
            flash("Acesso negado: Esta área é restrita a Gerentes.", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated_function

# ---------------------------------------------------------
# FUNÇÃO DE AUDITORIA (LOGS)
# ---------------------------------------------------------
def registrar_log(acao, detalhes):
    try:
        db.collection("logs_auditoria").add({
            "usuario_nome": session.get("nome", "Desconhecido"),
            "usuario_email": session.get("email", "Sem conta"),
            "acao": acao,
            "detalhes": detalhes,
            "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        })
    except Exception as e:
        print(f"Erro ao registrar log: {e}")

# ---------------------------------------------------------
# ROTAS DE AUTENTICAÇÃO
# ---------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip()
        senha = request.form["senha"].strip()
        
        if email == "gerente@techstore.com" and senha == "123456":
            session["usuario_id"] = "gerente_id"
            session["nome"] = "Gerente TechStore"
            session["email"] = email
            session["perfil"] = "GERENTE"
            flash("Login realizado com sucesso!", "success")
            return redirect(url_for("index"))
        elif email == "operador@techstore.com" and senha == "123456":
            session["usuario_id"] = "operador_id"
            session["nome"] = "Operador WMS"
            session["email"] = email
            session["perfil"] = "OPERADOR"
            flash("Login realizado com sucesso!", "success")
            return redirect(url_for("index"))
            
        usuarios_ref = db.collection("usuarios").where("email", "==", email).where("senha", "==", senha).stream()
        usuario_doc = next(usuarios_ref, None)
        
        if usuario_doc:
            dados = usuario_doc.to_dict()
            session["usuario_id"] = usuario_doc.id
            session["nome"] = dados.get("nome", "Usuário")
            session["email"] = dados.get("email", email)
            session["perfil"] = dados.get("perfil", "OPERADOR")
            flash("Login realizado com sucesso!", "success")
            return redirect(url_for("index"))
        else:
            flash("E-mail ou senha incorretos.", "danger")
            
    return render_template("login.html")

@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if request.method == "POST":
        nome = request.form["nome"].strip()
        email = request.form["email"].strip()
        senha = request.form["senha"].strip()
        perfil = request.form.get("perfil", "OPERADOR")
        
        try:
            usuarios_ref = db.collection("usuarios").where("email", "==", email).stream()
            if list(usuarios_ref):
                flash("Este e-mail já está cadastrado.", "danger")
                return redirect(url_for("cadastro"))
            
            db.collection("usuarios").add({
                "nome": nome,
                "email": email,
                "senha": senha,
                "perfil": perfil
            })
            registrar_log("Criou Conta", f"Novo usuário cadastrado: {email} ({perfil})")
            flash("Conta criada com sucesso! Faça login.", "success")
            return redirect(url_for("login"))
        except Exception as e:
            flash(f"Erro ao criar conta: {e}", "danger")
            
    return render_template("cadastro.html")

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
        
    produtos_ref = db.collection("produtos").stream()
    produtos = []
    for doc in produtos_ref:
        p = doc.to_dict()
        p["id_produto"] = doc.id
        p.setdefault("categoria", "Geral")
        p.setdefault("fornecedor", "Padrão")
        produtos.append(p)
        
    return render_template("index.html", produtos=produtos)

# ---------------------------------------------------------
# CADASTRAR NOVO PRODUTO (EXCLUSIVO GERENTE)
# ---------------------------------------------------------
@app.route("/produto/novo", methods=["GET", "POST"])
@gerente_required
def novo_produto():
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
            
            registrar_log("Cadastrou SKU", f"Produto: {nome_comercial} | SKU: {sku} | Qtd: {quantidade_estoque}")
            
            flash("Ativo cadastrado com sucesso no Firebase!", "success")
            return redirect(url_for("index"))
        except Exception as e:
            flash(f"Erro ao inserir no Firebase: {e}", "danger")
            return redirect(url_for("novo_produto"))

    categorias = [{"id_categoria": "Hardware", "nome": "Hardware"}, {"id_categoria": "Software", "nome": "Software"}]
    fornecedores = [{"id_fornecedor": "Principal", "razao_social": "Fornecedor Principal Ltda"}]
    return render_template("form_produto.html", categorias=categorias, fornecedores=fornecedores)

# ---------------------------------------------------------
# MOVIMENTAÇÃO DE ESTOQUE (OPERADOR E GERENTE)
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
        nome_prod = dados.get("nome_comercial", "Produto")

        if tipo_operacao == "Saída" and quantidade > saldo_atual:
            flash(f"Operação Bloqueada: Saldo insuficiente. Disponível: {saldo_atual} unidades.", "danger")
            return redirect(url_for("movimentacao"))

        novo_saldo = saldo_atual + quantidade if tipo_operacao == "Entrada" else saldo_atual - quantidade

        try:
            prod_ref.update({"quantidade_estoque": novo_saldo})
            db.collection("movimentacoes").add({
                "id_produto": id_produto,
                "tipo_operacao": tipo_operacao,
                "quantidade": quantidade,
                "justificativa": justificativa,
                "data": firestore.SERVER_TIMESTAMP
            })
            
            registrar_log(f"Movimentação ({tipo_operacao})", f"Produto: {nome_prod} | Qtd: {quantidade} | Motivo: {justificativa}")
            
            flash("Movimentação consolidada com sucesso no Firebase!", "success")
            return redirect(url_for("index"))
        except Exception as e:
            flash(f"Erro ao processar movimentação: {e}", "danger")

    produtos_ref = db.collection("produtos").stream()
    produtos = [{"id_produto": d.id, **d.to_dict()} for d in produtos_ref]
    return render_template("form_movimentacao.html", produtos=produtos)

# ---------------------------------------------------------
# GERENCIAMENTO DE USUÁRIOS E AUDITORIA (EXCLUSIVO GERENTE)
# ---------------------------------------------------------
@app.route("/usuarios")
@gerente_required
def listar_usuarios():
    usuarios_ref = db.collection("usuarios").stream()
    lista_usuarios = []
    for doc in usuarios_ref:
        u = doc.to_dict()
        u["id"] = doc.id
        lista_usuarios.append(u)
        
    # Pega os últimos 20 logs de auditoria para exibir no painel
    logs_ref = db.collection("logs_auditoria").order_by("data_hora", direction=firestore.Query.DESCENDING).limit(20).stream()
    logs = [log.to_dict() for log in logs_ref]
    
    return render_template("usuarios.html", usuarios=lista_usuarios, logs=logs)

@app.route("/usuarios/excluir/<usuario_id>", methods=["POST"])
@gerente_required
def excluir_usuario(usuario_id):
    if usuario_id == session.get("usuario_id"):
        flash("Você não pode excluir a sua própria conta logada!", "danger")
        return redirect(url_for("listar_usuarios"))
    
    try:
        user_doc = db.collection("usuarios").document(usuario_id).get()
        user_email = user_doc.to_dict().get("email", "Desconhecido") if user_doc.exists else "Desconhecido"
        
        db.collection("usuarios").document(usuario_id).delete()
        registrar_log("Excluiu Usuário", f"Colaborador removido do sistema: {user_email}")
        flash("Acesso do colaborador removido com sucesso!", "success")
    except Exception as e:
        flash(f"Erro ao excluir usuário: {e}", "danger")
        
    return redirect(url_for("listar_usuarios"))

# ---------------------------------------------------------
# CHECKOUT / PDV (OPERADOR E GERENTE)
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
            nomes_produtos_vendidos = []
            
            for i in range(len(produtos_ids)):
                p_id = produtos_ids[i]
                qtd = int(quantidades[i])
                
                prod_ref = db.collection("produtos").document(p_id)
                doc = prod_ref.get()
                
                if not doc.exists:
                    raise Exception(f"Produto ID {p_id} não encontrado!")
                
                prod_data = doc.to_dict()
                estoque_atual = int(prod_data.get("quantidade_estoque", 0))
                nome_prod = prod_data.get('nome_comercial', '')
                
                if estoque_atual < qtd:
                    raise Exception(f"Estoque insuficiente para o produto {nome_prod}!")
                
                preco_unitario = float(prod_data.get("preco_venda", 0))
                subtotal = preco_unitario * qtd
                valor_total_venda += subtotal
                
                nomes_produtos_vendidos.append(f"{qtd}x {nome_prod}")
                
                itens_a_faturar.append({
                    "produto_id": p_id,
                    "quantidade": qtd,
                    "preco_unitario": preco_unitario,
                    "subtotal": subtotal,
                    "estoque_atual": estoque_atual,
                    "nome": nome_prod
                })
            
            numero_pedido = f"PED-2026-{abs(hash(cliente_documento + str(valor_total_venda))) % 10000:04d}"
            
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
            
            registrar_log("Realizou Venda (Checkout)", f"Pedido {numero_pedido} | Cliente: {cliente_nome} | Total: R$ {valor_total_venda:.2f}")
            
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
    
    itens_stream = db.collection("itens_venda").where("venda_id", "==", venda_id).stream()
    itens = []
    for item_doc in itens_stream:
        i = item_doc.to_dict()
        p_doc = db.collection("produtos").document(i["produto_id"]).get()
        nome_prod = p_doc.to_dict().get("nome_comercial", "Produto") if p_doc.exists else "Produto"
        itens.append((nome_prod, i["quantidade_vendida"], i["preco_unitario_praticado"], i["subtotal_item"]))
    
    return render_template("recibo.html", venda=venda, itens=itens)

# ---------------------------------------------------------
# EXCLUSÃO DE ATIVO (EXCLUSIVO GERENTE)
# ---------------------------------------------------------
@app.route('/produto/excluir-selecionado', methods=['POST'])
@gerente_required
def excluir_selecionado():
    id_produto = request.form.get("id_produto")
    if not id_produto:
        flash("Nenhum produto selecionado.", "danger")
        return redirect(url_for('index'))
        
    try:
        prod_doc = db.collection("produtos").document(id_produto).get()
        nome_prod = prod_doc.to_dict().get("nome_comercial", "Desconhecido") if prod_doc.exists else "Desconhecido"
        sku_prod = prod_doc.to_dict().get("sku", "N/A") if prod_doc.exists else "N/A"
        
        db.collection("produtos").document(id_produto).delete()
        
        registrar_log("Excluiu Produto", f"Produto removido: {nome_prod} (SKU: {sku_prod})")
        
        flash("Ativo excluído com sucesso do Firebase!", "success")
    except Exception as e:
        flash(f"Erro ao excluir ativo: {e}", "danger")
        
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)