# import g4f as g4f
# from g4f.requests import curl_cffi

task = '''
Найди скорость выполнения кода и результаты замера используемой памяти в битах данного кода
def linear_search(target: int, search_list: list) -> list:
  to_return = []  # Initialize an empty list for indexes
  for i in range(len(search_list)):
    if search_list[i] == target:  # Check if the current element matches the target
      to_return.append(i)  # If found, append the index to the return list
  if len(to_return) == 0:  # If the target id not in search_list
    return [-1]
  return to_return
На данных тестах
test_input = [
            (1000, list(range(-1000, -800))+list(range(800, 1001))),
            (3, list(range(-1000, 4))+[3, 3, 3, 3]+list(range(600, 700))+list(range(3, 650))),
            (250, list(range(200, 400))+list(range(100, 300))+list(range(300, -150, -1))),
            (-500, list(range(-550, -450))+list(range(-550, -450))+list(range(-550, -450))),
            (100, [100 for i in range(100)]),
            (0, [3, 2, 4, 0] * 5),
            (-2, [3, 2, 4, 0] * 5)
        ]
'''


try:
    from g4f.client import Client
    client = Client()
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": task}],
    )
    message = response.choices[0].message.content
    print(message)

except Exception as e:
    print(e)


# myenv\Scripts\activate.bat