import openai
from openai import OpenAI
import pdfplumber
import json
import re
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.http import FileResponse
import tempfile
import pandas as pd
import statistics

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

class GetExcel(APIView):
    def post(self, request):
        try:
            # Verificar archivo subido
            pdf_file = request.FILES.get('file')
            if not pdf_file:
                return Response({"error": "No se proporcionó un archivo"}, status=status.HTTP_400_BAD_REQUEST)

            print(f"📎 Archivo recibido: {pdf_file.name}")

            # Extraer texto estructurado del PDF
            extracted_text = self.extract_text_from_pdf(pdf_file)
            if not extracted_text:
                return Response({"error": "No se pudo extraer texto del archivo PDF."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            print("Texto extraído:", extracted_text)

            # Crear cliente de OpenAI
            client = OpenAI(api_key= OPENAI_API_KEY)

            # Enviar el texto al modelo GPT-4
            response = client.responses.create(
                model="gpt-4-0125-preview",
                input=[
                    {
                        "role": "system",
                        "content": "Actuás como un modelo especializado en análisis automático de facturas de electricidad en Argentina. Tu única tarea es leer el texto plano extraído de una factura eléctrica (proporcionado por el usuario) y devolver un objeto JSON estandarizado, simple y útil para tareas básicas de análisis.\n\n🎯 OBJETIVO\nConvertir cualquier factura de luz en un objeto JSON simple con los datos mínimos esenciales. No es necesario interpretar formatos complejos, solo leer y estructurar información clara del texto.\n\n📋 REGLAS ESTRICTAS\n- No inventar datos ni completar con suposiciones.\n- Si un dato no aparece explícitamente, devolver `null`\n- Responder siempre exclusivamente con un JSON válido. Sin explicaciones, sin texto adicional.\n- Usar **exactamente** los nombres de campo definidos en el esquema.\n- Las fechas deben estar en formato `dd/mm/yyyy`.\n- Los valores numéricos deben conservar su formato tal como aparecen (por ejemplo: `1.234,56`).\n\n📦 FORMATO JSON DE RESPUESTA:\n```json\n{\n  \"customer_info\": {\n    \"customer_name\": \"\",\n    \"supply_address\": \"\",\n    \"tariff_type\": \"\"\n  },\n  \"billing_info\": {\n    \"issue_date\": \"\",\n    \"due_date\": \"\"\n  },\n  \"meter_readings\": {\n    \"consumed_kwh\": null\n  },\n  \"totals\": {\n    \"total_billed\": null\n  }\n}\n```\n\n⚙️ DETALLES:\n- `tariff_type`: solo permitir estos valores si aparecen: `\"Residencial\"`, `\"Comercial\"`, `\"Industrial\"`.\n- `consumed_kwh`: debe provenir del texto, como \"Consumo facturado\" o similar.\n- `total_billed`: valor total a pagar, puede aparecer como \"Total a pagar\", \"Importe total\" o similar.\n- Si un campo está ausente en el texto, dejarlo como `null`, **no lo calcules ni lo infieras**.\n\n🧪 MODO DE USO\nEl usuario enviará el contenido extraído de la factura como texto plano. Devolvé únicamente el objeto JSON completo, según el esquema, con los valores extraídos.\n\n🚫 PROHIBIDO:\n- No incluir explicaciones.\n- No comentar tu respuesta.\n- No agregar texto adicional.\n- No adivinar información.\n\n✅ SOLO RESPONDER CON UN JSON SIMPLE Y VÁLIDO. Nada más."
                    },
                    {
                        "role": "user",
                        "content": extracted_text  # Aquí se incluye el texto extraído del PDF
                    }
                ],
                temperature=1,
                max_output_tokens=2048,
                top_p=1,
                store=True
            )

            # Procesar la respuesta
            output = response.output_text
            print(f"📥 Respuesta del modelo: {output}")

            # Extraer el JSON de la respuesta usando una expresión regular
            try:
                json_match = re.search(r"\{.*\}", output, re.DOTALL)
                if not json_match:
                    raise ValueError("No se encontró un JSON válido en la respuesta del modelo.")
                json_result = json.loads(json_match.group(0))
                print("✅ JSON recibido:", json_result)
            except (json.JSONDecodeError, ValueError) as e:
                print(f"Error al parsear JSON: {str(e)}")
                return Response({"error": "Respuesta no es JSON válido", "raw": output}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # Generar archivo Excel
            excel_path = self.generate_excel(json_result)

            return FileResponse(open(excel_path, 'rb'), as_attachment=True, filename='factura_generada.xlsx')

        except Exception as e:
            print(f"💥 Error inesperado: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def extract_text_from_pdf(self, pdf_file):
        """Extrae texto estructurado de un archivo PDF."""
        text = ""
        try:
            with pdfplumber.open(pdf_file) as pdf:
                for page_number, page in enumerate(pdf.pages, 1):
                    words = page.extract_words(
                        extra_attrs=["size", "fontname"],
                        keep_blank_chars=False,
                        use_text_flow=True
                    )

                    if not words:
                        continue

                    words.sort(key=lambda x: (x["top"], x["x0"]))

                    lines = []
                    current_line = []
                    current_top = words[0]["top"]

                    for word in words:
                        if abs(word["top"] - current_top) > 5:
                            lines.append(current_line)
                            current_line = []
                            current_top = word["top"]
                        current_line.append(word)

                    if current_line:
                        lines.append(current_line)

                    font_sizes = [word["size"] for line in lines for word in line]
                    try:
                        common_size = statistics.mode(font_sizes)
                    except statistics.StatisticsError:
                        common_size = max(set(font_sizes), key=font_sizes.count)

                    for line in lines:
                        line_text = " ".join(word["text"] for word in line)
                        avg_size = sum(word["size"] for word in line) / len(line)
                        is_bold = any(word.get("bold", False) for word in line)

                        if avg_size > common_size * 1.3 or is_bold:
                            text += f"\n★ TÍTULO: {line_text}\n"
                        elif avg_size > common_size * 1.1:
                            text += f"\n• {line_text}\n"
                        else:
                            text += line_text + " "

                    text += "\n" + "=" * 50 + "\n"

            return text.strip()
        except Exception as e:
            print(f"❌ Error al procesar el archivo PDF: {e}")
            return None

    def generate_excel(self, data: dict) -> str:
        """Genera un archivo Excel a partir de un JSON estructurado."""

        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                print("❌ El JSON recibido no es válido.")
                return None

        print("✅ JSON convertido correctamente.")

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
        path = tmp.name
        tmp.close()

        # Info del cliente
        customer = data.get('customer_info', {})
        cliente_df = pd.DataFrame([{
            'Nombre': customer.get('customer_name'),
            'Dirección': customer.get('supply_address'),
            'Tipo de Tarifa': customer.get('tariff_type'),
        }])

        # Factura
        bill = data.get('billing_info', {})
        factura_df = pd.DataFrame([{
            'Fecha de Emisión': bill.get('issue_date'),
            'Fecha de Vencimiento': bill.get('due_date'),
        }])

        # Lecturas del medidor
        readings = data.get('meter_readings', {})
        lecturas_df = pd.DataFrame([{
            'Consumo Total (kWh)': readings.get('consumed_kwh'),
        }])

        # Totales
        totals = data.get('totals', {})
        totales_df = pd.DataFrame([{
            'Total Facturado': totals.get('total_billed'),
        }])

        # Escribir en Excel
        with pd.ExcelWriter(path, engine='openpyxl') as writer:
            cliente_df.to_excel(writer, sheet_name='Cliente', index=False)
            factura_df.to_excel(writer, sheet_name='Factura', index=False)
            lecturas_df.to_excel(writer, sheet_name='Lecturas', index=False)
            totales_df.to_excel(writer, sheet_name='Totales', index=False)

        print(f"✅ Excel generado en: {path}")
        return path