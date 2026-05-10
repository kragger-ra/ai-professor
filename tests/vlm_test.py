from transformers import AutoModelForCausalLM, AutoTokenizer
from PIL import Image
import time
import torch

print(torch.cuda.is_available())
model_id = "vikhyatk/moondream2"
revision = "2024-08-26"   
model = AutoModelForCausalLM.from_pretrained(
    model_id, trust_remote_code=True, revision=revision,
    torch_dtype=torch.float16, attn_implementation="flash_attention_2"
).to("cuda")

tokenizer = AutoTokenizer.from_pretrained(model_id, revision=revision)

start_time = time.time()
image = Image.open('maxresdefault.jpg')
enc_image = model.encode_image(image)
print(model.answer_question(enc_image, "What am i doing?", tokenizer))
print("--- %s seconds ---" % (time.time() - start_time))